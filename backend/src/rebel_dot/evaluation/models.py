from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rebel_dot.domain import GuardrailReason, Route, ScopeDecision


class EvaluationCategory(StrEnum):
    FAQ_PARAPHRASE = "faq_paraphrase"
    NEAR_NEIGHBOR = "near_neighbor"
    TECHNICAL_FALLBACK = "technical_fallback"
    COMPLIANCE = "compliance"
    MALFORMED = "malformed"
    INJECTION = "injection"
    BENIGN_GUARDRAIL = "benign_guardrail"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CollectionDescriptor(StrictModel):
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    fixture: str = Field(min_length=1)
    record_count: int = Field(gt=0)


class EvaluationCase(StrictModel):
    id: str = Field(min_length=1)
    category: EvaluationCategory
    question: str
    expected_route: Route
    expected_scope: ScopeDecision | None
    expected_question: str | None
    attack: bool
    expect_guardrail_block: bool

    @model_validator(mode="after")
    def validate_labels(self) -> "EvaluationCase":
        if self.expected_route is Route.ERROR and not self.expect_guardrail_block:
            raise ValueError("error routes must expect a guardrail block")
        if self.expected_route is not Route.ERROR and self.expect_guardrail_block:
            raise ValueError("non-error routes cannot expect a guardrail block")
        if self.attack and self.category is not EvaluationCategory.INJECTION:
            raise ValueError("attack cases must use the injection category")
        return self


class EvaluationDataset(StrictModel):
    dataset_version: str = Field(min_length=1)
    created_at: str = Field(min_length=1)
    taxonomy_version: str = Field(min_length=1)
    collection: CollectionDescriptor
    cases: tuple[EvaluationCase, ...] = Field(min_length=1)


class CandidateObservation(StrictModel):
    question: str = Field(min_length=1)
    similarity: float = Field(ge=0, le=1)


class GuardrailObservation(StrictModel):
    allowed: bool
    reason: GuardrailReason | None

    @model_validator(mode="after")
    def validate_reason(self) -> "GuardrailObservation":
        if self.allowed and self.reason is not None:
            raise ValueError("allowed guardrail observations cannot have a reason")
        if not self.allowed and self.reason is None:
            raise ValueError("blocked guardrail observations require a reason")
        return self


class ScopeObservation(StrictModel):
    decision: ScopeDecision
    confidence: float = Field(ge=0, le=1)


class ReviewScore(StrictModel):
    reviewer: str = Field(min_length=1)
    relevance: int = Field(ge=1, le=5)
    correctness: int = Field(ge=1, le=5)
    clarity: int = Field(ge=1, le=5)
    safety: int = Field(ge=1, le=5)
    consistency: int = Field(ge=1, le=5)
    unsupported_claim: bool


class CaseObservation(StrictModel):
    case_id: str = Field(min_length=1)
    guardrail: GuardrailObservation
    scope: ScopeObservation | None
    candidates: tuple[CandidateObservation, ...]
    schema_valid: bool = True
    latency_ms: float = Field(ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float = Field(default=0, ge=0)
    answer: str | None = None
    reviews: tuple[ReviewScore, ...] = ()

    @model_validator(mode="after")
    def validate_observation(self) -> "CaseObservation":
        if self.guardrail.allowed and self.scope is None:
            raise ValueError("allowed observations require a scope result")
        if any(
            left.similarity < right.similarity
            for left, right in zip(self.candidates, self.candidates[1:], strict=False)
        ):
            raise ValueError("candidate observations must be ordered by similarity")
        if self.reviews and not self.answer:
            raise ValueError("reviewed observations require an answer")
        return self


class ObservationSet(StrictModel):
    observation_version: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    captured_at: str = Field(min_length=1)
    source: str = Field(min_length=1)
    models: dict[str, str]
    prompts: dict[str, str]
    cases: tuple[CaseObservation, ...] = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class EvaluationBundle:
    dataset: EvaluationDataset
    observations: ObservationSet
    dataset_path: Path
    observations_path: Path
