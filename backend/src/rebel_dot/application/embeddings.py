from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from rebel_dot.domain import (
    CollectionStatus,
    EmbeddingJob,
    EmbeddingJobStatus,
    EmbeddingProviderError,
    FAQCollection,
    FAQItem,
    OptimisticConcurrencyError,
    RetrievalCandidate,
)
from rebel_dot.domain.content import normalize_question
from rebel_dot.ports import EmbeddingProvider, UnitOfWork


def utc_now() -> datetime:
    return datetime.now(UTC)


class EmbeddingJobService:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock

    async def queue(self, collection_id: UUID) -> EmbeddingJob:
        now = self._clock()
        async with self._unit_of_work_factory() as unit_of_work:
            collection = await unit_of_work.collections.get(collection_id)
            if collection is None:
                raise LookupError(f"FAQ collection {collection_id} does not exist")
            pending = await unit_of_work.faqs.list_pending_embeddings(collection_id)
            items = await unit_of_work.faqs.list_by_collection(collection_id)
            has_active_items = any(item.is_active for item in items)
            status = EmbeddingJobStatus.QUEUED if pending else EmbeddingJobStatus.COMPLETED
            job = EmbeddingJob(
                id=uuid4(),
                collection_id=collection_id,
                status=status,
                requested_count=len(pending),
                processed_count=0,
                failed_count=0,
                error_summary=None,
                created_at=now,
                started_at=None,
                completed_at=now if not pending else None,
            )
            await unit_of_work.jobs.add(job)
            if collection.status is not CollectionStatus.ACTIVE:
                target_status = (
                    CollectionStatus.EMBEDDING
                    if pending
                    else CollectionStatus.READY
                    if has_active_items
                    else CollectionStatus.DRAFT
                )
                await unit_of_work.collections.set_status(
                    collection_id,
                    target_status.value,
                    now,
                )
            return job

    async def get(self, job_id: UUID) -> EmbeddingJob | None:
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.jobs.get(job_id)


class DatabaseEmbeddingRunner:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        provider: EmbeddingProvider,
        batch_size: int,
        stale_after_seconds: int = 300,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._provider = provider
        self._batch_size = batch_size
        self._stale_after = timedelta(seconds=stale_after_seconds)
        self._clock = clock

    async def run_once(self) -> bool:
        started_at = self._clock()
        async with self._unit_of_work_factory() as unit_of_work:
            job = await unit_of_work.jobs.claim_next(
                started_at,
                started_at - self._stale_after,
            )
        if job is None:
            return False

        try:
            await self._run_job(job)
        except LookupError:
            async with self._unit_of_work_factory() as unit_of_work:
                await unit_of_work.jobs.fail(job.id, "Collection is unavailable", self._clock())
        except Exception:
            async with self._unit_of_work_factory() as unit_of_work:
                await unit_of_work.jobs.fail(job.id, "Embedding job failed", self._clock())
        return True

    async def _run_job(self, job: EmbeddingJob) -> None:
        collection, items = await self._load_work(job)

        items = items[: job.requested_count]
        processed_count = max(0, job.requested_count - len(items))
        failed_count = 0
        error_summary: str | None = None
        if processed_count:
            await self._record_progress(
                job.id,
                processed_count,
                failed_count,
                error_summary,
            )

        for batch_start in range(0, len(items), self._batch_size):
            batch = items[batch_start : batch_start + self._batch_size]
            try:
                vectors = await self._provider.embed(
                    tuple(item.question_normalized for item in batch)
                )
            except EmbeddingProviderError:
                failed_count += len(batch)
                error_summary = "Embedding provider unavailable"
                await self._record_progress(
                    job.id,
                    processed_count,
                    failed_count,
                    error_summary,
                )
                continue

            batch_processed, batch_failed = await self._store_batch(
                job,
                collection,
                batch,
                vectors,
            )
            processed_count += batch_processed
            failed_count += batch_failed
            if batch_failed:
                error_summary = "Content changed during embedding"
            await self._record_progress(
                job.id,
                processed_count,
                failed_count,
                error_summary,
            )

        await self._finish(job.id, collection)

    async def run_until_idle(self) -> None:
        while await self.run_once():
            pass

    async def _load_work(
        self,
        job: EmbeddingJob,
    ) -> tuple[FAQCollection, tuple[FAQItem, ...]]:
        async with self._unit_of_work_factory() as unit_of_work:
            collection = await unit_of_work.collections.get(job.collection_id)
            if collection is None:
                raise LookupError
            pending = await unit_of_work.faqs.list_pending_embeddings(job.collection_id)
            return collection, tuple(pending)

    async def _store_batch(
        self,
        job: EmbeddingJob,
        collection: FAQCollection,
        batch: Sequence[FAQItem],
        vectors: Sequence[Sequence[float]],
    ) -> tuple[int, int]:
        processed = 0
        failed = 0
        embedded_at = self._clock()
        async with self._unit_of_work_factory() as unit_of_work:
            for item, vector in zip(batch, vectors, strict=True):
                try:
                    await unit_of_work.faqs.store_embedding(
                        item.id,
                        vector,
                        collection.embedding_model,
                        item.content_hash,
                        embedded_at,
                    )
                except OptimisticConcurrencyError:
                    failed += 1
                else:
                    processed += 1
        return processed, failed

    async def _record_progress(
        self,
        job_id: UUID,
        processed_count: int,
        failed_count: int,
        error_summary: str | None,
    ) -> None:
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.jobs.record_progress(
                job_id,
                processed_count,
                failed_count,
                error_summary,
            )

    async def _finish(self, job_id: UUID, collection: FAQCollection) -> None:
        completed_at = self._clock()
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.jobs.complete(job_id, completed_at)
            remaining = await unit_of_work.faqs.list_pending_embeddings(collection.id)
            if not remaining and collection.status is not CollectionStatus.ACTIVE:
                await unit_of_work.collections.set_status(
                    collection.id,
                    CollectionStatus.READY.value,
                    completed_at,
                )


class RetrievalService:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        provider: EmbeddingProvider,
        embedding_model: str,
        embedding_dimensions: int,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._provider = provider
        self._embedding_model = embedding_model
        self._embedding_dimensions = embedding_dimensions

    async def search(self, question: str, limit: int = 3) -> Sequence[RetrievalCandidate]:
        vectors = await self._provider.embed((normalize_question(question),))
        query_vector = vectors[0]
        async with self._unit_of_work_factory() as unit_of_work:
            collection = await unit_of_work.collections.get_active()
            if collection is None:
                return ()
            if (
                collection.embedding_model != self._embedding_model
                or collection.embedding_dimensions != self._embedding_dimensions
            ):
                return ()
            return await unit_of_work.faqs.search(collection.id, query_vector, limit)
