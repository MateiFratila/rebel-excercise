from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from rebel_dot.domain import (
    AnswerSource,
    CollectionStatus,
    EmbeddingJobStatus,
    ErrorCode,
)


class TransportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AskQuestionRequest(TransportModel):
    user_question: str = Field(min_length=1, max_length=2000)


class AskQuestionResponse(TransportModel):
    source: AnswerSource
    matched_question: str | None
    answer: str


class ErrorDetail(TransportModel):
    code: ErrorCode
    message: str
    request_id: str


class ErrorResponse(TransportModel):
    error: ErrorDetail


class CreateSessionRequest(TransportModel):
    password: str = Field(min_length=1, max_length=1024)


class CreateCollectionRequest(TransportModel):
    name: str = Field(min_length=1, max_length=200)
    embedding_model: str = Field(min_length=1, max_length=100)
    embedding_dimensions: int = Field(ge=1, le=3072)


class CollectionResponse(TransportModel):
    id: UUID
    name: str
    version: int
    status: CollectionStatus
    embedding_model: str
    embedding_dimensions: int
    created_at: datetime
    updated_at: datetime
    readiness: "CollectionReadinessResponse"


class CollectionReadinessResponse(TransportModel):
    ready: bool
    active_items: int
    pending_items: int


class FAQItemInput(TransportModel):
    question: str = Field(min_length=1, max_length=4000)
    answer: str = Field(min_length=1, max_length=16000)
    category: str = Field(min_length=1, max_length=100)
    source_metadata: dict[str, object] = Field(default_factory=dict)


class BulkUpsertFAQItemsRequest(TransportModel):
    items: list[FAQItemInput] = Field(min_length=1, max_length=1000)


class BulkUpsertFAQItemsResponse(TransportModel):
    changed_count: int


class UpdateFAQItemRequest(FAQItemInput):
    expected_updated_at: datetime


class FAQItemResponse(TransportModel):
    id: UUID
    collection_id: UUID
    question: str
    answer: str
    category: str
    source_metadata: dict[str, object]
    is_active: bool
    embedding_model: str | None
    embedded_at: datetime | None
    created_at: datetime
    updated_at: datetime


class EmbeddingJobResponse(TransportModel):
    job_id: UUID
    status: EmbeddingJobStatus
    requested_count: int
    processed_count: int
    failed_count: int
    error_summary: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
