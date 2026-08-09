import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from rebel_dot.adapters.db.database import create_database_engine, create_session_factory
from rebel_dot.adapters.db.models import (
    EmbeddingJobRecord,
    FAQCollectionRecord,
    FAQItemRecord,
)
from rebel_dot.adapters.db.unit_of_work import SQLAlchemyUnitOfWork
from rebel_dot.application.embeddings import (
    DatabaseEmbeddingRunner,
    EmbeddingJobService,
    RetrievalService,
)
from rebel_dot.application.knowledge import (
    CollectionNotReadyError,
    FAQItemDraft,
    KnowledgeService,
)
from rebel_dot.domain import CollectionStatus, EmbeddingJobStatus

pytestmark = pytest.mark.integration


class DeterministicEmbeddingProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        self.calls.append(texts)
        return tuple(self._vector(text) for text in texts)

    @staticmethod
    def _vector(text: str) -> tuple[float, ...]:
        normalized = text.casefold()
        if "password" in normalized:
            return (1.0, 0.0, 0.0)
        if "email" in normalized:
            return (0.0, 1.0, 0.0)
        return (0.0, 0.0, 1.0)


@pytest.fixture
async def unit_of_work_factory():  # type: ignore[no-untyped-def]
    database_url = os.getenv("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is required for knowledge integration tests")

    engine = create_database_engine(database_url)
    session_factory = create_session_factory(engine)
    async with engine.begin() as connection:
        await connection.execute(delete(EmbeddingJobRecord))
        await connection.execute(delete(FAQItemRecord))
        await connection.execute(delete(FAQCollectionRecord))

    yield lambda: SQLAlchemyUnitOfWork(session_factory)

    async with engine.begin() as connection:
        await connection.execute(delete(EmbeddingJobRecord))
        await connection.execute(delete(FAQItemRecord))
        await connection.execute(delete(FAQCollectionRecord))
    await engine.dispose()


async def test_create_embed_activate_retrieve_and_incremental_update(
    unit_of_work_factory,  # type: ignore[no-untyped-def]
) -> None:
    current_time = datetime(2026, 8, 9, 12, tzinfo=UTC)

    def clock() -> datetime:
        return current_time

    provider = DeterministicEmbeddingProvider()
    knowledge = KnowledgeService(
        unit_of_work_factory=unit_of_work_factory,
        embedding_model="test-embedding",
        embedding_dimensions=3,
        clock=clock,
    )
    jobs = EmbeddingJobService(
        unit_of_work_factory=unit_of_work_factory,
        clock=clock,
    )
    runner = DatabaseEmbeddingRunner(
        unit_of_work_factory=unit_of_work_factory,
        provider=provider,
        batch_size=2,
        clock=clock,
    )
    retrieval = RetrievalService(
        unit_of_work_factory=unit_of_work_factory,
        provider=provider,
        embedding_model="test-embedding",
        embedding_dimensions=3,
    )

    collection = await knowledge.create_collection("support", "test-embedding", 3)
    drafts = (
        FAQItemDraft(
            question="How do I reset my password?",
            answer="Use the reset form.",
            category="security",
            source_metadata={},
        ),
        FAQItemDraft(
            question="How do I change my email?",
            answer="Open account settings.",
            category="profile",
            source_metadata={},
        ),
        FAQItemDraft(
            question="The app crashes on launch",
            answer="Update and restart it.",
            category="troubleshooting",
            source_metadata={},
        ),
    )
    assert await knowledge.upsert_items(collection.id, drafts) == 3
    assert await knowledge.upsert_items(collection.id, drafts) == 0

    readiness = await knowledge.readiness(collection.id)
    assert readiness.active_items == 3
    assert readiness.pending_items == 3
    assert not readiness.ready
    with pytest.raises(CollectionNotReadyError):
        await knowledge.activate(collection.id)

    job = await jobs.queue(collection.id)
    assert job.status is EmbeddingJobStatus.QUEUED
    assert job.requested_count == 3
    assert await runner.run_once()
    assert not await runner.run_once()
    assert [len(batch) for batch in provider.calls] == [2, 1]
    assert {text for batch in provider.calls for text in batch} == {
        "How do I reset my password?",
        "How do I change my email?",
        "The app crashes on launch",
    }

    completed = await jobs.get(job.id)
    assert completed is not None
    assert completed.status is EmbeddingJobStatus.COMPLETED
    assert completed.processed_count == 3
    assert completed.failed_count == 0
    assert (await knowledge.readiness(collection.id)).ready
    assert (await knowledge.activate(collection.id)).status is CollectionStatus.ACTIVE

    provider.calls.clear()
    candidates = await retrieval.search("I forgot my password")
    assert candidates[0].question == "How do I reset my password?"
    assert candidates[0].answer == "Use the reset form."
    assert candidates[0].similarity == pytest.approx(1.0)
    assert provider.calls == [("I forgot my password",)]

    items = await knowledge.list_items(collection.id)
    password_item = next(item for item in items if "password" in item.question_raw)
    current_time += timedelta(seconds=1)
    await knowledge.update_item(
        collection.id,
        password_item.id,
        password_item.updated_at,
        FAQItemDraft(
            question=password_item.question_raw,
            answer="Use the secure password reset form.",
            category=password_item.category,
            source_metadata=password_item.source_metadata,
        ),
    )
    assert (await knowledge.readiness(collection.id)).pending_items == 1

    provider.calls.clear()
    incremental_job = await jobs.queue(collection.id)
    assert incremental_job.requested_count == 1
    duplicate_job = await jobs.queue(collection.id)
    assert duplicate_job.requested_count == 1
    await runner.run_until_idle()
    assert provider.calls == [("How do I reset my password?",)]
    completed_duplicate = await jobs.get(duplicate_job.id)
    assert completed_duplicate is not None
    assert completed_duplicate.status is EmbeddingJobStatus.COMPLETED
    assert completed_duplicate.processed_count == 1

    no_op_job = await jobs.queue(collection.id)
    assert no_op_job.status is EmbeddingJobStatus.COMPLETED
    await runner.run_until_idle()
    assert provider.calls == [("How do I reset my password?",)]

    await knowledge.deactivate_item(collection.id, password_item.id)
    remaining = await retrieval.search("I forgot my password")
    assert all(candidate.item_id != password_item.id for candidate in remaining)
