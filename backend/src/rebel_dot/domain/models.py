from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID


class CollectionStatus(StrEnum):
    DRAFT = "draft"
    EMBEDDING = "embedding"
    READY = "ready"
    ACTIVE = "active"
    ARCHIVED = "archived"


class EmbeddingJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIALLY_FAILED = "partially_failed"
    FAILED = "failed"


class AnswerSource(StrEnum):
    LOCAL = "local"
    OPENAI = "openai"
    COMPLIANCE = "compliance"


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "validation_error"
    AUTHENTICATION_REQUIRED = "authentication_required"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    RATE_LIMITED = "rate_limited"
    UPSTREAM_INVALID_RESPONSE = "upstream_invalid_response"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    UPSTREAM_TIMEOUT = "upstream_timeout"
    INTERNAL_ERROR = "internal_error"


class Route(StrEnum):
    LOCAL = "local"
    OPENAI = "openai"
    COMPLIANCE = "compliance"
    ERROR = "error"


class ScopeDecision(StrEnum):
    IN_DOMAIN = "in_domain"
    OUT_OF_DOMAIN = "out_of_domain"
    UNCERTAIN = "uncertain"


class GuardrailReason(StrEnum):
    EMPTY_INPUT = "empty_input"
    INPUT_TOO_LONG = "input_too_long"
    UNSUPPORTED_CHARACTERS = "unsupported_characters"
    PROMPT_INJECTION = "prompt_injection"
    SECRET_EXFILTRATION = "secret_exfiltration"
    ENCODED_PAYLOAD = "encoded_payload"
    EMPTY_OUTPUT = "empty_output"
    OUTPUT_TOO_LONG = "output_too_long"
    SECRET_LEAK = "secret_leak"
    HIDDEN_PROMPT_DISCLOSURE = "hidden_prompt_disclosure"
    UNSUPPORTED_ACTION_CLAIM = "unsupported_action_claim"


@dataclass(frozen=True, slots=True)
class FAQCollection:
    id: UUID
    name: str
    version: int
    status: CollectionStatus
    embedding_model: str
    embedding_dimensions: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class FAQItem:
    id: UUID
    collection_id: UUID
    question_raw: str
    question_normalized: str
    answer_raw: str
    category: str
    content_hash: str
    source_metadata: Mapping[str, object]
    embedding: tuple[float, ...] | None
    embedding_model: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    embedded_at: datetime | None


@dataclass(frozen=True, slots=True)
class EmbeddingJob:
    id: UUID
    collection_id: UUID
    status: EmbeddingJobStatus
    requested_count: int
    processed_count: int
    failed_count: int
    error_summary: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class AuthSession:
    id: UUID
    token_digest: str
    expires_at: datetime
    created_at: datetime
    revoked_at: datetime | None
    last_seen_at: datetime | None


@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    item_id: UUID
    question: str
    answer: str
    category: str
    similarity: float


@dataclass(frozen=True, slots=True)
class GuardrailResult:
    allowed: bool
    reason: GuardrailReason | None = None


@dataclass(frozen=True, slots=True)
class ScopeResult:
    decision: ScopeDecision
    confidence: float


@dataclass(frozen=True, slots=True)
class RoutingEvidence:
    guardrail: GuardrailResult
    scope: ScopeResult
    candidates: tuple[RetrievalCandidate, ...]


@dataclass(frozen=True, slots=True)
class WorkflowState:
    raw_question: str
    normalized_question: str | None = None
    guardrail: GuardrailResult | None = None
    scope: ScopeResult | None = None
    candidates: tuple[RetrievalCandidate, ...] = ()
    route: Route | None = None
    answer: str | None = None
    diagnostics: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True, slots=True)
class QuestionAnswer:
    source: AnswerSource
    matched_question: str | None
    answer: str
