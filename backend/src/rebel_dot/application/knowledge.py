from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from rebel_dot.domain import CollectionStatus, FAQCollection, FAQItem
from rebel_dot.domain.content import compute_content_hash, normalize_question
from rebel_dot.ports import UnitOfWork


class CollectionNotReadyError(Exception):
    pass


class IncompatibleCollectionError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class FAQItemDraft:
    question: str
    answer: str
    category: str
    source_metadata: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class CollectionReadiness:
    active_items: int
    pending_items: int

    @property
    def ready(self) -> bool:
        return self.active_items > 0 and self.pending_items == 0


def utc_now() -> datetime:
    return datetime.now(UTC)


class KnowledgeService:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        embedding_model: str,
        embedding_dimensions: int,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._embedding_model = embedding_model
        self._embedding_dimensions = embedding_dimensions
        self._clock = clock

    async def list_collections(
        self,
    ) -> tuple[tuple[FAQCollection, CollectionReadiness], ...]:
        async with self._unit_of_work_factory() as unit_of_work:
            collections = await unit_of_work.collections.list()
            result: list[tuple[FAQCollection, CollectionReadiness]] = []
            for collection in collections:
                readiness = await self._readiness(unit_of_work, collection.id)
                result.append((collection, readiness))
            return tuple(result)

    async def create_collection(
        self,
        name: str,
        embedding_model: str,
        embedding_dimensions: int,
    ) -> FAQCollection:
        self._require_compatible(embedding_model, embedding_dimensions)
        now = self._clock()
        async with self._unit_of_work_factory() as unit_of_work:
            existing = await unit_of_work.collections.list()
            version = (
                max(
                    (collection.version for collection in existing if collection.name == name),
                    default=0,
                )
                + 1
            )
            collection = FAQCollection(
                id=uuid4(),
                name=name,
                version=version,
                status=CollectionStatus.DRAFT,
                embedding_model=embedding_model,
                embedding_dimensions=embedding_dimensions,
                created_at=now,
                updated_at=now,
            )
            await unit_of_work.collections.add(collection)
            return collection

    async def list_items(self, collection_id: UUID) -> Sequence[FAQItem]:
        async with self._unit_of_work_factory() as unit_of_work:
            await self._require_collection(unit_of_work, collection_id)
            return await unit_of_work.faqs.list_by_collection(collection_id)

    async def get_item(self, collection_id: UUID, item_id: UUID) -> FAQItem:
        async with self._unit_of_work_factory() as unit_of_work:
            item = await unit_of_work.faqs.get(item_id)
            if item is None or item.collection_id != collection_id:
                raise LookupError(f"FAQ item {item_id} does not exist")
            return item

    async def upsert_items(
        self,
        collection_id: UUID,
        drafts: Sequence[FAQItemDraft],
    ) -> int:
        now = self._clock()
        items = tuple(self._build_item(collection_id, draft, now) for draft in drafts)
        async with self._unit_of_work_factory() as unit_of_work:
            collection = await self._require_collection(unit_of_work, collection_id)
            changed_count = await unit_of_work.faqs.upsert_many(items)
            if changed_count and collection.status is not CollectionStatus.ACTIVE:
                await unit_of_work.collections.set_status(
                    collection_id,
                    CollectionStatus.DRAFT.value,
                    now,
                )
            return changed_count

    async def update_item(
        self,
        collection_id: UUID,
        item_id: UUID,
        expected_updated_at: datetime,
        draft: FAQItemDraft,
    ) -> FAQItem:
        now = self._clock()
        async with self._unit_of_work_factory() as unit_of_work:
            collection = await self._require_collection(unit_of_work, collection_id)
            current = await unit_of_work.faqs.get(item_id)
            if current is None or current.collection_id != collection_id:
                raise LookupError(f"FAQ item {item_id} does not exist")
            updated = replace(
                current,
                question_raw=draft.question,
                question_normalized=normalize_question(draft.question),
                answer_raw=draft.answer,
                category=draft.category,
                content_hash=compute_content_hash(
                    draft.question,
                    draft.answer,
                    draft.category,
                ),
                source_metadata=dict(draft.source_metadata),
                updated_at=now,
            )
            stored = await unit_of_work.faqs.update(updated, expected_updated_at)
            if (
                stored.content_hash != current.content_hash
                and collection.status is not CollectionStatus.ACTIVE
            ):
                await unit_of_work.collections.set_status(
                    collection_id,
                    CollectionStatus.DRAFT.value,
                    now,
                )
            return stored

    async def deactivate_item(self, collection_id: UUID, item_id: UUID) -> FAQItem:
        async with self._unit_of_work_factory() as unit_of_work:
            collection = await self._require_collection(unit_of_work, collection_id)
            current = await unit_of_work.faqs.get(item_id)
            if current is None or current.collection_id != collection_id:
                raise LookupError(f"FAQ item {item_id} does not exist")
            now = self._clock()
            deactivated = await unit_of_work.faqs.deactivate(item_id, now)
            if collection.status is not CollectionStatus.ACTIVE:
                readiness = await self._readiness(unit_of_work, collection_id)
                target_status = (
                    CollectionStatus.READY if readiness.ready else CollectionStatus.DRAFT
                )
                await unit_of_work.collections.set_status(
                    collection_id,
                    target_status.value,
                    now,
                )
            return deactivated

    async def readiness(self, collection_id: UUID) -> CollectionReadiness:
        async with self._unit_of_work_factory() as unit_of_work:
            collection = await self._require_collection(unit_of_work, collection_id)
            self._require_compatible(
                collection.embedding_model,
                collection.embedding_dimensions,
            )
            return await self._readiness(unit_of_work, collection_id)

    async def activate(self, collection_id: UUID) -> FAQCollection:
        now = self._clock()
        async with self._unit_of_work_factory() as unit_of_work:
            collection = await self._require_collection(unit_of_work, collection_id)
            self._require_compatible(
                collection.embedding_model,
                collection.embedding_dimensions,
            )
            readiness = await self._readiness(unit_of_work, collection_id)
            if not readiness.ready:
                raise CollectionNotReadyError(f"FAQ collection {collection_id} is not ready")
            return await unit_of_work.collections.activate(collection_id, now)

    async def application_ready(self) -> bool:
        async with self._unit_of_work_factory() as unit_of_work:
            collection = await unit_of_work.collections.get_active()
            if collection is None:
                return False
            try:
                self._require_compatible(
                    collection.embedding_model,
                    collection.embedding_dimensions,
                )
            except IncompatibleCollectionError:
                return False
            return (await self._readiness(unit_of_work, collection.id)).ready

    async def _readiness(
        self,
        unit_of_work: UnitOfWork,
        collection_id: UUID,
    ) -> CollectionReadiness:
        items = await unit_of_work.faqs.list_by_collection(collection_id)
        pending = await unit_of_work.faqs.list_pending_embeddings(collection_id)
        return CollectionReadiness(
            active_items=sum(item.is_active for item in items),
            pending_items=len(pending),
        )

    async def _require_collection(
        self,
        unit_of_work: UnitOfWork,
        collection_id: UUID,
    ) -> FAQCollection:
        collection = await unit_of_work.collections.get(collection_id)
        if collection is None:
            raise LookupError(f"FAQ collection {collection_id} does not exist")
        return collection

    def _require_compatible(self, model: str, dimensions: int) -> None:
        if model != self._embedding_model or dimensions != self._embedding_dimensions:
            raise IncompatibleCollectionError(
                "collection embedding configuration does not match the runtime"
            )

    @staticmethod
    def _build_item(collection_id: UUID, draft: FAQItemDraft, now: datetime) -> FAQItem:
        return FAQItem(
            id=uuid4(),
            collection_id=collection_id,
            question_raw=draft.question,
            question_normalized=normalize_question(draft.question),
            answer_raw=draft.answer,
            category=draft.category,
            content_hash=compute_content_hash(draft.question, draft.answer, draft.category),
            source_metadata=dict(draft.source_metadata),
            embedding=None,
            embedding_model=None,
            is_active=True,
            created_at=now,
            updated_at=now,
            embedded_at=None,
        )
