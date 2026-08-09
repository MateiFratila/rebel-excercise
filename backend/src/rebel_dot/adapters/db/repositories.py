from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import cast as sql_cast
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from rebel_dot.adapters.db.models import (
    AuthSessionRecord,
    EmbeddingJobRecord,
    FAQCollectionRecord,
    FAQItemRecord,
)
from rebel_dot.domain import (
    AuthSession,
    CollectionStatus,
    EmbeddingJob,
    EmbeddingJobStatus,
    FAQCollection,
    FAQItem,
    OptimisticConcurrencyError,
    RetrievalCandidate,
)


def _collection_from_record(record: FAQCollectionRecord) -> FAQCollection:
    return FAQCollection(
        id=record.id,
        name=record.name,
        version=record.version,
        status=CollectionStatus(record.status),
        embedding_model=record.embedding_model,
        embedding_dimensions=record.embedding_dimensions,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _faq_from_record(record: FAQItemRecord) -> FAQItem:
    vector = None if record.embedding is None else tuple(float(value) for value in record.embedding)
    return FAQItem(
        id=record.id,
        collection_id=record.collection_id,
        question_raw=record.question_raw,
        question_normalized=record.question_normalized,
        answer_raw=record.answer_raw,
        category=record.category,
        content_hash=record.content_hash,
        source_metadata=dict(record.source_metadata),
        embedding=vector,
        embedding_model=record.embedding_model,
        is_active=record.is_active,
        created_at=record.created_at,
        updated_at=record.updated_at,
        embedded_at=record.embedded_at,
    )


def _job_from_record(record: EmbeddingJobRecord) -> EmbeddingJob:
    return EmbeddingJob(
        id=record.id,
        collection_id=record.collection_id,
        status=EmbeddingJobStatus(record.status),
        requested_count=record.requested_count,
        processed_count=record.processed_count,
        failed_count=record.failed_count,
        error_summary=record.error_summary,
        created_at=record.created_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
    )


def _session_from_record(record: AuthSessionRecord) -> AuthSession:
    return AuthSession(
        id=record.id,
        token_digest=record.token_digest,
        expires_at=record.expires_at,
        created_at=record.created_at,
        revoked_at=record.revoked_at,
        last_seen_at=record.last_seen_at,
    )


class SQLAlchemyCollectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self) -> Sequence[FAQCollection]:
        records = await self._session.scalars(
            select(FAQCollectionRecord).order_by(FAQCollectionRecord.created_at)
        )
        return tuple(_collection_from_record(record) for record in records)

    async def get(self, collection_id: UUID) -> FAQCollection | None:
        record = await self._session.get(FAQCollectionRecord, collection_id)
        return None if record is None else _collection_from_record(record)

    async def get_active(self) -> FAQCollection | None:
        record = await self._session.scalar(
            select(FAQCollectionRecord).where(
                FAQCollectionRecord.status == CollectionStatus.ACTIVE.value
            )
        )
        return None if record is None else _collection_from_record(record)

    async def add(self, collection: FAQCollection) -> None:
        self._session.add(
            FAQCollectionRecord(
                id=collection.id,
                name=collection.name,
                version=collection.version,
                status=collection.status.value,
                embedding_model=collection.embedding_model,
                embedding_dimensions=collection.embedding_dimensions,
                created_at=collection.created_at,
                updated_at=collection.updated_at,
            )
        )

    async def set_status(
        self,
        collection_id: UUID,
        status: str,
        updated_at: datetime,
    ) -> FAQCollection:
        collection_status = CollectionStatus(status)
        if collection_status is CollectionStatus.ACTIVE:
            raise ValueError("use activate to set an active collection")
        record = await self._session.get(FAQCollectionRecord, collection_id, with_for_update=True)
        if record is None:
            raise LookupError(f"FAQ collection {collection_id} does not exist")
        record.status = collection_status.value
        record.updated_at = updated_at
        await self._session.flush()
        return _collection_from_record(record)

    async def activate(self, collection_id: UUID, updated_at: datetime) -> FAQCollection:
        records = await self._session.scalars(
            select(FAQCollectionRecord)
            .where(
                or_(
                    FAQCollectionRecord.id == collection_id,
                    FAQCollectionRecord.status == CollectionStatus.ACTIVE.value,
                )
            )
            .with_for_update()
        )
        target: FAQCollectionRecord | None = None
        for record in records:
            if record.id == collection_id:
                target = record
            elif record.status == CollectionStatus.ACTIVE.value:
                record.status = CollectionStatus.ARCHIVED.value
                record.updated_at = updated_at

        if target is None:
            raise LookupError(f"FAQ collection {collection_id} does not exist")

        await self._session.flush()
        target.status = CollectionStatus.ACTIVE.value
        target.updated_at = updated_at
        await self._session.flush()
        return _collection_from_record(target)


class SQLAlchemyFAQRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_collection(self, collection_id: UUID) -> Sequence[FAQItem]:
        records = await self._session.scalars(
            select(FAQItemRecord)
            .where(FAQItemRecord.collection_id == collection_id)
            .order_by(FAQItemRecord.created_at, FAQItemRecord.id)
        )
        return tuple(_faq_from_record(record) for record in records)

    async def list_pending_embeddings(self, collection_id: UUID) -> Sequence[FAQItem]:
        records = await self._session.scalars(
            select(FAQItemRecord)
            .join(
                FAQCollectionRecord,
                FAQCollectionRecord.id == FAQItemRecord.collection_id,
            )
            .where(
                FAQItemRecord.collection_id == collection_id,
                FAQItemRecord.is_active.is_(True),
                (
                    FAQItemRecord.embedding.is_(None)
                    | (FAQItemRecord.embedding_model != FAQCollectionRecord.embedding_model)
                    | (FAQItemRecord.embedded_content_hash != FAQItemRecord.content_hash)
                ),
            )
            .order_by(FAQItemRecord.created_at, FAQItemRecord.id)
        )
        return tuple(_faq_from_record(record) for record in records)

    async def get(self, item_id: UUID) -> FAQItem | None:
        record = await self._session.get(FAQItemRecord, item_id)
        return None if record is None else _faq_from_record(record)

    async def upsert_many(self, items: Sequence[FAQItem]) -> int:
        if not items:
            return 0

        collection_ids = {item.collection_id for item in items}
        if len(collection_ids) != 1:
            raise ValueError("one upsert batch cannot span collections")

        collection_id = next(iter(collection_ids))
        hashes = [item.content_hash for item in items]
        existing_records = await self._session.scalars(
            select(FAQItemRecord).where(
                FAQItemRecord.collection_id == collection_id,
                FAQItemRecord.content_hash.in_(hashes),
            )
        )
        existing_by_hash = {record.content_hash: record for record in existing_records}
        changed_count = 0

        for item in items:
            existing = existing_by_hash.get(item.content_hash)
            if existing is None:
                self._session.add(
                    FAQItemRecord(
                        id=item.id,
                        collection_id=item.collection_id,
                        question_raw=item.question_raw,
                        question_normalized=item.question_normalized,
                        answer_raw=item.answer_raw,
                        category=item.category,
                        content_hash=item.content_hash,
                        source_metadata=dict(item.source_metadata),
                        embedding=None if item.embedding is None else list(item.embedding),
                        embedding_model=item.embedding_model,
                        embedded_content_hash=(
                            item.content_hash if item.embedding is not None else None
                        ),
                        is_active=item.is_active,
                        created_at=item.created_at,
                        updated_at=item.updated_at,
                        embedded_at=item.embedded_at,
                    )
                )
                changed_count += 1
                continue

            metadata = dict(item.source_metadata)
            if existing.is_active != item.is_active or existing.source_metadata != metadata:
                existing.is_active = item.is_active
                existing.source_metadata = metadata
                existing.updated_at = item.updated_at
                changed_count += 1

        await self._session.flush()
        return changed_count

    async def update(
        self,
        item: FAQItem,
        expected_updated_at: datetime,
    ) -> FAQItem:
        record = await self._session.get(FAQItemRecord, item.id, with_for_update=True)
        if record is None:
            raise LookupError(f"FAQ item {item.id} does not exist")
        if record.updated_at != expected_updated_at:
            raise OptimisticConcurrencyError(f"FAQ item {item.id} was modified")
        if record.collection_id != item.collection_id:
            raise ValueError("FAQ item cannot move between collections")

        content_changed = record.content_hash != item.content_hash
        record.question_raw = item.question_raw
        record.question_normalized = item.question_normalized
        record.answer_raw = item.answer_raw
        record.category = item.category
        record.content_hash = item.content_hash
        record.source_metadata = dict(item.source_metadata)
        record.is_active = item.is_active
        record.updated_at = item.updated_at
        if content_changed:
            record.embedding = None
            record.embedding_model = None
            record.embedded_content_hash = None
            record.embedded_at = None

        await self._session.flush()
        return _faq_from_record(record)

    async def deactivate(self, item_id: UUID, updated_at: datetime) -> FAQItem:
        record = await self._session.get(FAQItemRecord, item_id, with_for_update=True)
        if record is None:
            raise LookupError(f"FAQ item {item_id} does not exist")
        record.is_active = False
        record.updated_at = updated_at
        await self._session.flush()
        return _faq_from_record(record)

    async def store_embedding(
        self,
        item_id: UUID,
        embedding: Sequence[float],
        embedding_model: str,
        expected_content_hash: str,
        embedded_at: datetime,
    ) -> FAQItem:
        record = await self._session.get(FAQItemRecord, item_id, with_for_update=True)
        if record is None:
            raise LookupError(f"FAQ item {item_id} does not exist")
        if record.content_hash != expected_content_hash:
            raise OptimisticConcurrencyError(f"FAQ item {item_id} content changed")
        record.embedding = [float(value) for value in embedding]
        record.embedding_model = embedding_model
        record.embedded_content_hash = record.content_hash
        record.embedded_at = embedded_at
        record.updated_at = embedded_at
        await self._session.flush()
        return _faq_from_record(record)

    async def search(
        self,
        collection_id: UUID,
        query_embedding: Sequence[float],
        limit: int,
    ) -> Sequence[RetrievalCandidate]:
        query_vector = [float(value) for value in query_embedding]
        if not query_vector:
            raise ValueError("query embedding cannot be empty")
        if limit < 1:
            raise ValueError("search limit must be positive")

        collection = await self._session.get(FAQCollectionRecord, collection_id)
        if collection is None:
            raise LookupError(f"FAQ collection {collection_id} does not exist")
        if collection.embedding_dimensions != len(query_vector):
            raise ValueError("query embedding dimensions do not match collection")

        vector = sql_cast(FAQItemRecord.embedding, Vector(len(query_vector)))
        distance = vector.cosine_distance(query_vector).label("distance")
        result = await self._session.execute(
            select(FAQItemRecord, distance)
            .where(
                FAQItemRecord.collection_id == collection_id,
                FAQItemRecord.is_active.is_(True),
                FAQItemRecord.embedding.is_not(None),
                FAQItemRecord.embedding_model == collection.embedding_model,
                func.vector_dims(FAQItemRecord.embedding) == len(query_vector),
                FAQItemRecord.embedded_content_hash == FAQItemRecord.content_hash,
            )
            .order_by(distance)
            .limit(limit)
        )
        rows = cast(Sequence[tuple[FAQItemRecord, Any]], result.all())
        return tuple(
            RetrievalCandidate(
                item_id=record.id,
                question=record.question_raw,
                answer=record.answer_raw,
                category=record.category,
                similarity=1.0 - float(raw_distance),
                collection_version=collection.version,
                embedding_model=collection.embedding_model,
            )
            for record, raw_distance in rows
        )


class SQLAlchemyEmbeddingJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, job: EmbeddingJob) -> None:
        self._session.add(
            EmbeddingJobRecord(
                id=job.id,
                collection_id=job.collection_id,
                status=job.status.value,
                requested_count=job.requested_count,
                processed_count=job.processed_count,
                failed_count=job.failed_count,
                error_summary=job.error_summary,
                created_at=job.created_at,
                started_at=job.started_at,
                completed_at=job.completed_at,
            )
        )

    async def get(self, job_id: UUID) -> EmbeddingJob | None:
        record = await self._session.get(EmbeddingJobRecord, job_id)
        return None if record is None else _job_from_record(record)

    async def claim_next(
        self,
        started_at: datetime,
        stale_before: datetime,
    ) -> EmbeddingJob | None:
        record = await self._session.scalar(
            select(EmbeddingJobRecord)
            .where(
                or_(
                    EmbeddingJobRecord.status == EmbeddingJobStatus.QUEUED.value,
                    (
                        (EmbeddingJobRecord.status == EmbeddingJobStatus.RUNNING.value)
                        & (EmbeddingJobRecord.started_at < stale_before)
                    ),
                )
            )
            .order_by(EmbeddingJobRecord.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if record is None:
            return None
        record.status = EmbeddingJobStatus.RUNNING.value
        record.started_at = started_at
        await self._session.flush()
        return _job_from_record(record)

    async def record_progress(
        self,
        job_id: UUID,
        processed_count: int,
        failed_count: int,
        error_summary: str | None = None,
    ) -> None:
        record = await self._require_job(job_id)
        record.processed_count = processed_count
        record.failed_count = failed_count
        record.error_summary = error_summary
        await self._session.flush()

    async def complete(self, job_id: UUID, completed_at: datetime) -> EmbeddingJob:
        record = await self._require_job(job_id)
        record.status = (
            EmbeddingJobStatus.COMPLETED.value
            if record.failed_count == 0
            else EmbeddingJobStatus.PARTIALLY_FAILED.value
        )
        record.completed_at = completed_at
        await self._session.flush()
        return _job_from_record(record)

    async def fail(
        self,
        job_id: UUID,
        error_summary: str,
        completed_at: datetime,
    ) -> EmbeddingJob:
        record = await self._require_job(job_id)
        record.status = EmbeddingJobStatus.FAILED.value
        record.error_summary = error_summary
        record.completed_at = completed_at
        await self._session.flush()
        return _job_from_record(record)

    async def _require_job(self, job_id: UUID) -> EmbeddingJobRecord:
        record = await self._session.get(EmbeddingJobRecord, job_id, with_for_update=True)
        if record is None:
            raise LookupError(f"Embedding job {job_id} does not exist")
        return record


class SQLAlchemySessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, session: AuthSession) -> None:
        self._session.add(
            AuthSessionRecord(
                id=session.id,
                token_digest=session.token_digest,
                expires_at=session.expires_at,
                created_at=session.created_at,
                revoked_at=session.revoked_at,
                last_seen_at=session.last_seen_at,
            )
        )

    async def count_active(self, now: datetime) -> int:
        count = await self._session.scalar(
            select(func.count(AuthSessionRecord.id)).where(
                AuthSessionRecord.expires_at > now,
                AuthSessionRecord.revoked_at.is_(None),
            )
        )
        return int(count or 0)

    async def get_by_digest(self, token_digest: str, now: datetime) -> AuthSession | None:
        record = await self._session.scalar(
            select(AuthSessionRecord)
            .where(
                AuthSessionRecord.token_digest == token_digest,
                AuthSessionRecord.expires_at > now,
                AuthSessionRecord.revoked_at.is_(None),
            )
            .with_for_update()
        )
        if record is None:
            return None
        record.last_seen_at = now
        await self._session.flush()
        return _session_from_record(record)

    async def revoke(self, token_digest: str, revoked_at: datetime) -> bool:
        record = await self._session.scalar(
            select(AuthSessionRecord)
            .where(
                AuthSessionRecord.token_digest == token_digest,
                AuthSessionRecord.revoked_at.is_(None),
            )
            .with_for_update()
        )
        if record is None:
            return False
        record.revoked_at = revoked_at
        await self._session.flush()
        return True

    async def prune_expired(self, now: datetime) -> int:
        expired_ids = tuple(
            await self._session.scalars(
                select(AuthSessionRecord.id).where(AuthSessionRecord.expires_at <= now)
            )
        )
        if not expired_ids:
            return 0
        await self._session.execute(
            delete(AuthSessionRecord).where(AuthSessionRecord.id.in_(expired_ids))
        )
        return len(expired_ids)
