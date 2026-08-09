import math
from collections import defaultdict
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field

from rebel_dot.application.routing import ConfidenceRoutingPolicy
from rebel_dot.domain import (
    GuardrailResult,
    RetrievalCandidate,
    Route,
    RoutingEvidence,
    ScopeDecision,
    ScopeResult,
)
from rebel_dot.evaluation.calibration import (
    CalibrationCase,
    CandidateScore,
    OperatingPoint,
    evaluate_operating_points,
    select_operating_point,
)
from rebel_dot.evaluation.models import (
    CaseObservation,
    EvaluationBundle,
    EvaluationCase,
    EvaluationCategory,
    StrictModel,
)

DEFAULT_SIMILARITY_THRESHOLDS = tuple(round(0.78 + index * 0.01, 2) for index in range(13))
DEFAULT_SIMILARITY_MARGINS = tuple(round(0.03 + index * 0.01, 2) for index in range(10))
DEFAULT_SCOPE_CONFIDENCE_THRESHOLD = 0.75


class RetrievalMetrics(StrictModel):
    evaluated_cases: int
    recall_at_1: float
    recall_at_3: float
    mean_reciprocal_rank: float


class RouteMetrics(StrictModel):
    evaluated_cases: int
    accuracy: float
    local_precision: float
    local_recall: float
    local_f1: float
    false_local_count: int
    false_local_rate: float


class ScopeMetrics(StrictModel):
    evaluated_cases: int
    accuracy: float
    in_domain_precision: float
    in_domain_recall: float
    in_domain_f1: float


class GuardrailMetrics(StrictModel):
    attack_cases: int
    attack_block_rate: float
    benign_cases: int
    benign_false_positive_rate: float


class SchemaMetrics(StrictModel):
    evaluated_cases: int
    valid_response_rate: float


class LatencyMetrics(StrictModel):
    p50_ms: float
    p95_ms: float


class UsageMetrics(StrictModel):
    case_count: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float


class SubjectiveMetrics(StrictModel):
    reviewed_answers: int
    review_count: int
    mean_relevance: float
    mean_correctness: float
    mean_clarity: float
    mean_safety: float
    mean_consistency: float
    unsupported_claim_rate: float


class WeakCase(StrictModel):
    case_id: str
    reason: str


class EvaluationReport(StrictModel):
    dataset_version: str
    observation_version: str
    captured_at: str
    observation_source: str
    taxonomy_version: str
    collection: dict[str, object]
    models: dict[str, str]
    prompts: dict[str, str]
    selected_operating_point: OperatingPoint
    scope_confidence_threshold: float
    sweep: tuple[OperatingPoint, ...] = Field(min_length=1)
    retrieval: RetrievalMetrics
    routing: RouteMetrics
    scope: ScopeMetrics
    guardrails: GuardrailMetrics
    schema_validity: SchemaMetrics
    latency: LatencyMetrics
    usage_by_route: dict[str, UsageMetrics]
    subjective_fallback: SubjectiveMetrics
    weak_cases: tuple[WeakCase, ...]
    limitations: tuple[str, ...]


def build_report(
    bundle: EvaluationBundle,
    *,
    similarity_thresholds: tuple[float, ...] = DEFAULT_SIMILARITY_THRESHOLDS,
    similarity_margins: tuple[float, ...] = DEFAULT_SIMILARITY_MARGINS,
    scope_confidence_threshold: float = DEFAULT_SCOPE_CONFIDENCE_THRESHOLD,
) -> EvaluationReport:
    observations = {observation.case_id: observation for observation in bundle.observations.cases}
    calibration_cases = tuple(
        CalibrationCase(
            case.id,
            case.expected_route,
            tuple(
                CandidateScore(candidate.question, candidate.similarity)
                for candidate in observations[case.id].candidates
            ),
            case.expected_question,
        )
        for case in bundle.dataset.cases
        if case.expected_route in {Route.LOCAL, Route.OPENAI}
    )
    sweep = evaluate_operating_points(
        calibration_cases,
        similarity_thresholds=similarity_thresholds,
        similarity_margins=similarity_margins,
    )
    selected = select_operating_point(
        calibration_cases,
        similarity_thresholds=similarity_thresholds,
        similarity_margins=similarity_margins,
    )
    routes = {
        case.id: _predict_route(
            case,
            observations[case.id],
            selected,
            scope_confidence_threshold,
        )
        for case in bundle.dataset.cases
    }
    return EvaluationReport(
        dataset_version=bundle.dataset.dataset_version,
        observation_version=bundle.observations.observation_version,
        captured_at=bundle.observations.captured_at,
        observation_source=bundle.observations.source,
        taxonomy_version=bundle.dataset.taxonomy_version,
        collection=bundle.dataset.collection.model_dump(mode="json"),
        models=bundle.observations.models,
        prompts=bundle.observations.prompts,
        selected_operating_point=selected,
        scope_confidence_threshold=scope_confidence_threshold,
        sweep=sweep,
        retrieval=_retrieval_metrics(bundle),
        routing=_route_metrics(bundle, observations, routes),
        scope=_scope_metrics(bundle, observations),
        guardrails=_guardrail_metrics(bundle, observations),
        schema_validity=_schema_metrics(bundle),
        latency=_latency_metrics(bundle),
        usage_by_route=_usage_metrics(bundle, observations, routes),
        subjective_fallback=_subjective_metrics(bundle),
        weak_cases=_weak_cases(bundle, observations, routes, selected),
        limitations=(
            "Observations use deterministic CI providers and recorded scores, "
            "not live OpenAI calls.",
            "Refresh the observation set with approved live-model captures before "
            "production tuning.",
            "Subjective review is a two-reviewer regression sample, not a broad human study.",
        ),
    )


def _predict_route(
    case: EvaluationCase,
    observation: CaseObservation,
    point: OperatingPoint,
    scope_confidence_threshold: float,
) -> Route:
    scope = observation.scope or _uncertain_scope()
    policy = ConfidenceRoutingPolicy(
        point.similarity_threshold,
        point.similarity_margin,
        scope_confidence_threshold,
    )
    return policy.select(
        RoutingEvidence(
            GuardrailResult(observation.guardrail.allowed, observation.guardrail.reason),
            ScopeResult(scope.decision, scope.confidence),
            tuple(
                RetrievalCandidate(
                    uuid5(NAMESPACE_URL, f"{case.id}:{index}:{candidate.question}"),
                    candidate.question,
                    "",
                    "evaluation",
                    candidate.similarity,
                )
                for index, candidate in enumerate(observation.candidates)
            ),
        )
    )


def _uncertain_scope() -> ScopeResult:
    return ScopeResult(ScopeDecision.UNCERTAIN, 0.0)


def _retrieval_metrics(bundle: EvaluationBundle) -> RetrievalMetrics:
    observations = {observation.case_id: observation for observation in bundle.observations.cases}
    ranks: list[int | None] = []
    for case in bundle.dataset.cases:
        if case.expected_question is None:
            continue
        rank = next(
            (
                index
                for index, candidate in enumerate(observations[case.id].candidates, start=1)
                if candidate.question == case.expected_question
            ),
            None,
        )
        ranks.append(rank)
    return RetrievalMetrics(
        evaluated_cases=len(ranks),
        recall_at_1=_ratio(sum(rank == 1 for rank in ranks), len(ranks)),
        recall_at_3=_ratio(sum(rank is not None and rank <= 3 for rank in ranks), len(ranks)),
        mean_reciprocal_rank=_ratio(
            sum(1 / rank for rank in ranks if rank is not None), len(ranks)
        ),
    )


def _route_metrics(
    bundle: EvaluationBundle,
    observations: dict[str, CaseObservation],
    routes: dict[str, Route],
) -> RouteMetrics:
    true_local = false_local = missed_local = correct = 0
    for case in bundle.dataset.cases:
        route = routes[case.id]
        candidates = observations[case.id].candidates
        top_question = candidates[0].question if candidates else None
        local_correct = (
            route is Route.LOCAL
            and case.expected_route is Route.LOCAL
            and top_question == case.expected_question
        )
        if local_correct:
            true_local += 1
        elif route is Route.LOCAL:
            false_local += 1
        if case.expected_route is Route.LOCAL and not local_correct:
            missed_local += 1
        if route is case.expected_route and (route is not Route.LOCAL or local_correct):
            correct += 1
    precision = _ratio(true_local, true_local + false_local)
    recall = _ratio(true_local, true_local + missed_local)
    return RouteMetrics(
        evaluated_cases=len(bundle.dataset.cases),
        accuracy=_ratio(correct, len(bundle.dataset.cases)),
        local_precision=precision,
        local_recall=recall,
        local_f1=_f1(precision, recall),
        false_local_count=false_local,
        false_local_rate=_ratio(false_local, len(bundle.dataset.cases)),
    )


def _scope_metrics(
    bundle: EvaluationBundle,
    observations: dict[str, CaseObservation],
) -> ScopeMetrics:
    cases = tuple(case for case in bundle.dataset.cases if case.expected_scope is not None)
    true_positive = false_positive = false_negative = correct = 0
    for case in cases:
        observed = observations[case.id].scope
        decision = observed.decision if observed is not None else ScopeDecision.UNCERTAIN
        if decision is case.expected_scope:
            correct += 1
        if decision is ScopeDecision.IN_DOMAIN and case.expected_scope is ScopeDecision.IN_DOMAIN:
            true_positive += 1
        elif decision is ScopeDecision.IN_DOMAIN:
            false_positive += 1
        elif case.expected_scope is ScopeDecision.IN_DOMAIN:
            false_negative += 1
    precision = _ratio(true_positive, true_positive + false_positive)
    recall = _ratio(true_positive, true_positive + false_negative)
    return ScopeMetrics(
        evaluated_cases=len(cases),
        accuracy=_ratio(correct, len(cases)),
        in_domain_precision=precision,
        in_domain_recall=recall,
        in_domain_f1=_f1(precision, recall),
    )


def _guardrail_metrics(
    bundle: EvaluationBundle,
    observations: dict[str, CaseObservation],
) -> GuardrailMetrics:
    attack_cases = tuple(case for case in bundle.dataset.cases if case.attack)
    benign_cases = tuple(
        case for case in bundle.dataset.cases if not case.attack and not case.expect_guardrail_block
    )
    blocked_attacks = sum(not observations[case.id].guardrail.allowed for case in attack_cases)
    blocked_benign = sum(not observations[case.id].guardrail.allowed for case in benign_cases)
    return GuardrailMetrics(
        attack_cases=len(attack_cases),
        attack_block_rate=_ratio(blocked_attacks, len(attack_cases)),
        benign_cases=len(benign_cases),
        benign_false_positive_rate=_ratio(blocked_benign, len(benign_cases)),
    )


def _schema_metrics(bundle: EvaluationBundle) -> SchemaMetrics:
    valid = sum(observation.schema_valid for observation in bundle.observations.cases)
    return SchemaMetrics(
        evaluated_cases=len(bundle.observations.cases),
        valid_response_rate=_ratio(valid, len(bundle.observations.cases)),
    )


def _latency_metrics(bundle: EvaluationBundle) -> LatencyMetrics:
    values = sorted(observation.latency_ms for observation in bundle.observations.cases)
    return LatencyMetrics(p50_ms=_percentile(values, 0.5), p95_ms=_percentile(values, 0.95))


def _usage_metrics(
    bundle: EvaluationBundle,
    observations: dict[str, CaseObservation],
    routes: dict[str, Route],
) -> dict[str, UsageMetrics]:
    grouped: dict[Route, list[CaseObservation]] = defaultdict(list)
    for case in bundle.dataset.cases:
        grouped[routes[case.id]].append(observations[case.id])
    return {
        route.value: UsageMetrics(
            case_count=len(items),
            input_tokens=sum(item.input_tokens for item in items),
            output_tokens=sum(item.output_tokens for item in items),
            estimated_cost_usd=round(sum(item.estimated_cost_usd for item in items), 8),
        )
        for route, items in sorted(grouped.items(), key=lambda pair: pair[0].value)
    }


def _subjective_metrics(bundle: EvaluationBundle) -> SubjectiveMetrics:
    reviewed = tuple(
        observation for observation in bundle.observations.cases if observation.reviews
    )
    reviews = tuple(review for observation in reviewed for review in observation.reviews)
    return SubjectiveMetrics(
        reviewed_answers=len(reviewed),
        review_count=len(reviews),
        mean_relevance=_mean(tuple(review.relevance for review in reviews)),
        mean_correctness=_mean(tuple(review.correctness for review in reviews)),
        mean_clarity=_mean(tuple(review.clarity for review in reviews)),
        mean_safety=_mean(tuple(review.safety for review in reviews)),
        mean_consistency=_mean(tuple(review.consistency for review in reviews)),
        unsupported_claim_rate=_ratio(
            sum(review.unsupported_claim for review in reviews), len(reviews)
        ),
    )


def _weak_cases(
    bundle: EvaluationBundle,
    observations: dict[str, CaseObservation],
    routes: dict[str, Route],
    point: OperatingPoint,
) -> tuple[WeakCase, ...]:
    weak: list[WeakCase] = []
    for case in bundle.dataset.cases:
        observation = observations[case.id]
        if routes[case.id] is not case.expected_route:
            weak.append(WeakCase(case_id=case.id, reason="route_mismatch"))
        if case.category is EvaluationCategory.NEAR_NEIGHBOR:
            weak.append(WeakCase(case_id=case.id, reason="ambiguous_near_neighbor"))
        if observation.candidates:
            top = observation.candidates[0].similarity
            if math.isclose(top, point.similarity_threshold, abs_tol=0.010001):
                weak.append(WeakCase(case_id=case.id, reason="similarity_boundary"))
            if len(observation.candidates) > 1:
                margin = top - observation.candidates[1].similarity
                if math.isclose(margin, point.similarity_margin, abs_tol=0.010001):
                    weak.append(WeakCase(case_id=case.id, reason="margin_boundary"))
    return tuple(weak)


def _ratio(numerator: int | float, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _f1(precision: float, recall: float) -> float:
    return round(2 * precision * recall / (precision + recall), 6) if precision + recall else 0.0


def _mean(values: tuple[int, ...]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    rank = max(1, math.ceil(quantile * len(values)))
    return values[rank - 1]
