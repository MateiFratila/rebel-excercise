from collections.abc import Sequence
from datetime import datetime
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from rebel_dot.domain import (
    AuthSession,
    EmbeddingJob,
    FAQCollection,
    FAQItem,
    GuardrailResult,
    QuestionAnswer,
    RetrievalCandidate,
    Route,
    RoutingEvidence,
    ScopeResult,
)


class EmbeddingProvider(Protocol):
    async def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


class ChatProvider(Protocol):
    async def answer(self, question: str) -> str: ...


class QuestionAnswerer(Protocol):
    async def ask(self, question: str) -> QuestionAnswer: ...


class FAQRetriever(Protocol):
    async def search(
        self,
        question: str,
        limit: int = 3,
    ) -> Sequence[RetrievalCandidate]: ...


class CollectionRepository(Protocol):
    async def list(self) -> Sequence[FAQCollection]: ...

    async def get(self, collection_id: UUID) -> FAQCollection | None: ...

    async def get_active(self) -> FAQCollection | None: ...

    async def add(self, collection: FAQCollection) -> None: ...

    async def set_status(
        self,
        collection_id: UUID,
        status: str,
        updated_at: datetime,
    ) -> FAQCollection: ...

    async def activate(self, collection_id: UUID, updated_at: datetime) -> FAQCollection: ...


class FAQRepository(Protocol):
    async def list_by_collection(self, collection_id: UUID) -> Sequence[FAQItem]: ...

    async def list_pending_embeddings(self, collection_id: UUID) -> Sequence[FAQItem]: ...

    async def get(self, item_id: UUID) -> FAQItem | None: ...

    async def upsert_many(self, items: Sequence[FAQItem]) -> int: ...

    async def update(
        self,
        item: FAQItem,
        expected_updated_at: datetime,
    ) -> FAQItem: ...

    async def deactivate(self, item_id: UUID, updated_at: datetime) -> FAQItem: ...

    async def store_embedding(
        self,
        item_id: UUID,
        embedding: Sequence[float],
        embedding_model: str,
        expected_content_hash: str,
        embedded_at: datetime,
    ) -> FAQItem: ...

    async def search(
        self,
        collection_id: UUID,
        query_embedding: Sequence[float],
        limit: int,
    ) -> Sequence[RetrievalCandidate]: ...


class EmbeddingJobRepository(Protocol):
    async def add(self, job: EmbeddingJob) -> None: ...

    async def get(self, job_id: UUID) -> EmbeddingJob | None: ...

    async def claim_next(
        self,
        started_at: datetime,
        stale_before: datetime,
    ) -> EmbeddingJob | None: ...

    async def record_progress(
        self,
        job_id: UUID,
        processed_count: int,
        failed_count: int,
        error_summary: str | None = None,
    ) -> None: ...

    async def complete(self, job_id: UUID, completed_at: datetime) -> EmbeddingJob: ...

    async def fail(
        self,
        job_id: UUID,
        error_summary: str,
        completed_at: datetime,
    ) -> EmbeddingJob: ...


class SessionRepository(Protocol):
    async def add(self, session: AuthSession) -> None: ...

    async def get_by_digest(self, token_digest: str, now: datetime) -> AuthSession | None: ...

    async def revoke(self, token_digest: str, revoked_at: datetime) -> bool: ...

    async def prune_expired(self, now: datetime) -> int: ...


class QuestionGuardrail(Protocol):
    async def evaluate(self, question: str) -> GuardrailResult: ...


class ScopeClassifier(Protocol):
    async def classify(self, question: str) -> ScopeResult: ...


class RoutingPolicy(Protocol):
    def select(self, evidence: RoutingEvidence) -> Route: ...


class TaskDispatcher(Protocol):
    async def dispatch_embedding_job(self, job_id: UUID) -> None: ...


class UnitOfWork(Protocol):
    @property
    def collections(self) -> CollectionRepository: ...

    @property
    def faqs(self) -> FAQRepository: ...

    @property
    def jobs(self) -> EmbeddingJobRepository: ...

    @property
    def sessions(self) -> SessionRepository: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...
