import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rebel_dot.adapters.db.database import create_database_engine, create_session_factory
from rebel_dot.adapters.db.unit_of_work import SQLAlchemyUnitOfWork
from rebel_dot.application.ingestion import import_faq_fixture
from rebel_dot.domain import (
    AuthSession,
    CollectionStatus,
    EmbeddingJob,
    EmbeddingJobStatus,
    FAQCollection,
    FAQItem,
    OptimisticConcurrencyError,
)
from rebel_dot.domain.content import compute_content_hash, normalize_question

pytestmark = pytest.mark.integration
FIXTURE_PATH = Path(__file__).parents[2] / "data" / "faq.json"


@pytest.fixture
async def session_factory() -> async_sessionmaker[AsyncSession]:
    database_url = os.getenv("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is required for repository integration tests")

    engine = create_database_engine(database_url)
    yield create_session_factory(engine)
    await engine.dispose()


def make_collection(
    now: datetime,
    *,
    collection_id: UUID | None = None,
    name: str,
    model: str,
    dimensions: int,
) -> FAQCollection:
    return FAQCollection(
        id=collection_id or uuid4(),
        name=name,
        version=1,
        status=CollectionStatus.DRAFT,
        embedding_model=model,
        embedding_dimensions=dimensions,
        created_at=now,
        updated_at=now,
    )


def make_item(
    collection_id: UUID,
    now: datetime,
    *,
    question: str,
    embedding: tuple[float, ...] | None = None,
    model: str | None = None,
) -> FAQItem:
    answer = f"Answer for {question}"
    category = "test"
    content_hash = compute_content_hash(question, answer, category)
    return FAQItem(
        id=uuid4(),
        collection_id=collection_id,
        question_raw=question,
        question_normalized=normalize_question(question),
        answer_raw=answer,
        category=category,
        content_hash=content_hash,
        source_metadata={},
        embedding=embedding,
        embedding_model=model,
        is_active=True,
        created_at=now,
        updated_at=now,
        embedded_at=now if embedding is not None else None,
    )


async def test_repository_lifecycle_and_constraints(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    support = make_collection(
        now,
        collection_id=UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
        name="support",
        model="text-embedding-3-small",
        dimensions=1536,
    )
    vectors = make_collection(
        now,
        collection_id=UUID("00000000-0000-0000-0000-000000000001"),
        name="vectors",
        model="test-embedding",
        dimensions=3,
    )
    unit_of_work = SQLAlchemyUnitOfWork(session_factory)

    async with unit_of_work as transaction:
        await transaction.collections.add(support)
        await transaction.collections.add(vectors)
        assert len(await transaction.collections.list()) == 2
        assert await transaction.collections.get_active() is None

    assert await import_faq_fixture(unit_of_work, support.id, FIXTURE_PATH, now) == 33
    assert await import_faq_fixture(unit_of_work, support.id, FIXTURE_PATH, now) == 0

    async with unit_of_work as transaction:
        imported = await transaction.faqs.list_by_collection(support.id)
        assert len(imported) == 33
        assert len(await transaction.faqs.list_pending_embeddings(support.id)) == 33
        assert any(item.question_raw == "help!!! 😭😭😭 my account is locked" for item in imported)

        active = await transaction.collections.activate(support.id, now)
        assert active.status is CollectionStatus.ACTIVE

    first_vector = make_item(
        vectors.id,
        now,
        question="First vector",
        embedding=(1.0, 0.0, 0.0),
        model="test-embedding",
    )
    second_vector = make_item(
        vectors.id,
        now,
        question="Second vector",
        embedding=(0.0, 1.0, 0.0),
        model="test-embedding",
    )

    async with unit_of_work as transaction:
        assert await transaction.faqs.upsert_many((first_vector, second_vector)) == 2
        candidates = await transaction.faqs.search(vectors.id, (1.0, 0.0, 0.0), 2)
        assert [candidate.question for candidate in candidates] == [
            "First vector",
            "Second vector",
        ]
        assert candidates[0].similarity == pytest.approx(1.0)

        deactivated = await transaction.faqs.deactivate(first_vector.id, now)
        assert not deactivated.is_active
        assert await transaction.faqs.get(first_vector.id) == deactivated

        activated = await transaction.collections.activate(vectors.id, now)
        assert activated.status is CollectionStatus.ACTIVE

    async with unit_of_work as transaction:
        assert (await transaction.collections.get_active()).id == vectors.id  # type: ignore[union-attr]
        assert (await transaction.collections.get(support.id)).status is CollectionStatus.ARCHIVED  # type: ignore[union-attr]
        remaining = await transaction.faqs.search(vectors.id, (1.0, 0.0, 0.0), 2)
        assert [candidate.question for candidate in remaining] == ["Second vector"]
        with pytest.raises(ValueError, match="cannot be empty"):
            await transaction.faqs.search(vectors.id, (), 1)
        with pytest.raises(ValueError, match="must be positive"):
            await transaction.faqs.search(vectors.id, (1.0, 0.0, 0.0), 0)
        with pytest.raises(ValueError, match="dimensions do not match"):
            await transaction.faqs.search(vectors.id, (1.0, 0.0), 2)

    invalid_vector = make_item(
        vectors.id,
        now,
        question="Wrong dimensions",
        embedding=(1.0, 0.0),
        model="test-embedding",
    )
    with pytest.raises(IntegrityError, match="dimensions do not match"):
        async with unit_of_work as transaction:
            await transaction.faqs.upsert_many((invalid_vector,))

    pending = make_item(vectors.id, now, question="Pending vector")
    async with unit_of_work as transaction:
        await transaction.faqs.upsert_many((pending,))
        stored = await transaction.faqs.store_embedding(
            pending.id,
            (0.0, 0.0, 1.0),
            "test-embedding",
            pending.content_hash,
            now,
        )
        assert stored.embedding == (0.0, 0.0, 1.0)
        assert pending.id not in {
            item.id for item in await transaction.faqs.list_pending_embeddings(vectors.id)
        }

    changed_at = now + timedelta(seconds=1)
    changed_pending = replace(
        stored,
        question_raw="Changed pending vector",
        question_normalized=normalize_question("Changed pending vector"),
        content_hash=compute_content_hash(
            "Changed pending vector",
            stored.answer_raw,
            stored.category,
        ),
        updated_at=changed_at,
    )
    async with unit_of_work as transaction:
        changed = await transaction.faqs.update(changed_pending, expected_updated_at=now)
        assert changed.embedding is None
        assert changed.embedding_model is None
        assert changed.embedded_at is None

    with pytest.raises(OptimisticConcurrencyError):
        async with unit_of_work as transaction:
            await transaction.faqs.update(changed_pending, expected_updated_at=now)

    job = EmbeddingJob(
        id=uuid4(),
        collection_id=vectors.id,
        status=EmbeddingJobStatus.QUEUED,
        requested_count=3,
        processed_count=0,
        failed_count=0,
        error_summary=None,
        created_at=now,
        started_at=None,
        completed_at=None,
    )
    async with unit_of_work as transaction:
        await transaction.jobs.add(job)
    async with unit_of_work as transaction:
        claimed = await transaction.jobs.claim_next(now, now - timedelta(minutes=5))
        assert claimed is not None and claimed.status is EmbeddingJobStatus.RUNNING
        await transaction.jobs.record_progress(job.id, processed_count=2, failed_count=1)
        completed = await transaction.jobs.complete(job.id, now)
        assert completed.status is EmbeddingJobStatus.PARTIALLY_FAILED
        assert await transaction.jobs.claim_next(now, now - timedelta(minutes=5)) is None

    failed_job = EmbeddingJob(
        id=uuid4(),
        collection_id=vectors.id,
        status=EmbeddingJobStatus.QUEUED,
        requested_count=1,
        processed_count=0,
        failed_count=0,
        error_summary=None,
        created_at=now + timedelta(seconds=1),
        started_at=None,
        completed_at=None,
    )
    async with unit_of_work as transaction:
        await transaction.jobs.add(failed_job)
    async with unit_of_work as transaction:
        await transaction.jobs.claim_next(now, now - timedelta(minutes=5))
        failed = await transaction.jobs.fail(failed_job.id, "provider unavailable", now)
        assert failed.status is EmbeddingJobStatus.FAILED
        assert (await transaction.jobs.get(failed_job.id)).error_summary == "provider unavailable"  # type: ignore[union-attr]

    stale_job = EmbeddingJob(
        id=uuid4(),
        collection_id=vectors.id,
        status=EmbeddingJobStatus.QUEUED,
        requested_count=1,
        processed_count=0,
        failed_count=0,
        error_summary=None,
        created_at=now + timedelta(seconds=2),
        started_at=None,
        completed_at=None,
    )
    async with unit_of_work as transaction:
        await transaction.jobs.add(stale_job)
    stale_started_at = now - timedelta(minutes=10)
    async with unit_of_work as transaction:
        first_claim = await transaction.jobs.claim_next(
            stale_started_at,
            stale_started_at - timedelta(minutes=5),
        )
        assert first_claim is not None and first_claim.id == stale_job.id
    async with unit_of_work as transaction:
        reclaimed = await transaction.jobs.claim_next(now, now - timedelta(minutes=5))
        assert reclaimed is not None and reclaimed.id == stale_job.id
        assert reclaimed.started_at == now
        await transaction.jobs.fail(stale_job.id, "recovery test complete", now)

    auth_session = AuthSession(
        id=uuid4(),
        token_digest="a" * 64,
        expires_at=now + timedelta(days=7),
        created_at=now,
        revoked_at=None,
        last_seen_at=None,
    )
    expired_session = AuthSession(
        id=uuid4(),
        token_digest="b" * 64,
        expires_at=now - timedelta(days=1),
        created_at=now - timedelta(days=2),
        revoked_at=None,
        last_seen_at=None,
    )
    async with unit_of_work as transaction:
        await transaction.sessions.add(auth_session)
        await transaction.sessions.add(expired_session)
    async with unit_of_work as transaction:
        resolved = await transaction.sessions.get_by_digest(auth_session.token_digest, now)
        assert resolved is not None and resolved.last_seen_at == now
        assert await transaction.sessions.count_active(now) == 1
        assert await transaction.sessions.revoke(auth_session.token_digest, now)
        assert await transaction.sessions.count_active(now) == 0
        assert not await transaction.sessions.revoke(auth_session.token_digest, now)
        assert await transaction.sessions.prune_expired(now) == 1
    async with unit_of_work as transaction:
        assert await transaction.sessions.get_by_digest(auth_session.token_digest, now) is None

    rolled_back = make_collection(now, name="rolled-back", model="test", dimensions=3)
    with pytest.raises(RuntimeError, match="force rollback"):
        async with unit_of_work as transaction:
            await transaction.collections.add(rolled_back)
            raise RuntimeError("force rollback")
    async with unit_of_work as transaction:
        assert await transaction.collections.get(rolled_back.id) is None
