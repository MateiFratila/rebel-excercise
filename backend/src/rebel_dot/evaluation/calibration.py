from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from rebel_dot.application.routing import ConfidenceRoutingPolicy
from rebel_dot.domain import (
    GuardrailResult,
    RetrievalCandidate,
    Route,
    RoutingEvidence,
    ScopeDecision,
    ScopeResult,
)


@dataclass(frozen=True, slots=True)
class CandidateScore:
    question: str
    similarity: float

    def __post_init__(self) -> None:
        if not self.question:
            raise ValueError("candidate question is required")
        if not 0 <= self.similarity <= 1:
            raise ValueError("candidate similarity must be between zero and one")


@dataclass(frozen=True, slots=True)
class CalibrationCase:
    case_id: str
    expected_route: Route
    candidates: tuple[CandidateScore, ...]
    expected_question: str | None = None

    def __post_init__(self) -> None:
        if not self.case_id:
            raise ValueError("case ID is required")
        if self.expected_route not in {Route.LOCAL, Route.OPENAI}:
            raise ValueError("calibration cases must expect local or OpenAI routing")
        if any(
            left.similarity < right.similarity
            for left, right in zip(self.candidates, self.candidates[1:], strict=False)
        ):
            raise ValueError("candidate scores must be ordered from highest to lowest")


@dataclass(frozen=True, slots=True)
class OperatingPoint:
    similarity_threshold: float
    similarity_margin: float
    local_precision: float
    local_recall: float
    local_f1: float
    false_local_count: int


def evaluate_operating_points(
    cases: tuple[CalibrationCase, ...],
    *,
    similarity_thresholds: tuple[float, ...],
    similarity_margins: tuple[float, ...],
) -> tuple[OperatingPoint, ...]:
    if not cases:
        raise ValueError("at least one calibration case is required")
    if not similarity_thresholds or not similarity_margins:
        raise ValueError("threshold and margin grids must not be empty")
    return tuple(
        _evaluate_point(cases, threshold, margin)
        for threshold in similarity_thresholds
        for margin in similarity_margins
    )


def select_operating_point(
    cases: tuple[CalibrationCase, ...],
    *,
    similarity_thresholds: tuple[float, ...],
    similarity_margins: tuple[float, ...],
) -> OperatingPoint:
    points = evaluate_operating_points(
        cases,
        similarity_thresholds=similarity_thresholds,
        similarity_margins=similarity_margins,
    )
    return max(
        points,
        key=lambda point: (
            point.local_precision,
            -point.false_local_count,
            point.local_recall,
            point.local_f1,
            -point.similarity_threshold,
            -point.similarity_margin,
        ),
    )


def _evaluate_point(
    cases: tuple[CalibrationCase, ...],
    similarity_threshold: float,
    similarity_margin: float,
) -> OperatingPoint:
    for name, value in (
        ("similarity threshold", similarity_threshold),
        ("similarity margin", similarity_margin),
    ):
        if not 0 <= value <= 1:
            raise ValueError(f"{name} must be between zero and one")

    policy = ConfidenceRoutingPolicy(similarity_threshold, similarity_margin, 0.75)
    true_local = false_local = missed_local = 0
    for case in cases:
        route = policy.select(
            RoutingEvidence(
                GuardrailResult(True),
                ScopeResult(ScopeDecision.IN_DOMAIN, 1.0),
                tuple(
                    RetrievalCandidate(
                        item_id=uuid5(
                            NAMESPACE_URL,
                            f"{case.case_id}:{index}:{candidate.question}",
                        ),
                        question=candidate.question,
                        answer="",
                        category="evaluation",
                        similarity=candidate.similarity,
                    )
                    for index, candidate in enumerate(case.candidates)
                ),
            )
        )
        predicted_local = route is Route.LOCAL
        matched_expected = (
            case.expected_question is None
            or bool(case.candidates)
            and case.candidates[0].question == case.expected_question
        )
        if predicted_local and case.expected_route is Route.LOCAL and matched_expected:
            true_local += 1
        elif predicted_local:
            false_local += 1
        if case.expected_route is Route.LOCAL and (not predicted_local or not matched_expected):
            missed_local += 1

    precision = true_local / (true_local + false_local) if true_local + false_local else 0.0
    recall = true_local / (true_local + missed_local) if true_local + missed_local else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return OperatingPoint(
        similarity_threshold=similarity_threshold,
        similarity_margin=similarity_margin,
        local_precision=precision,
        local_recall=recall,
        local_f1=f1,
        false_local_count=false_local,
    )
