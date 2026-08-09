from pathlib import Path

import pytest

from rebel_dot.domain import Route
from rebel_dot.evaluation import (
    CalibrationCase,
    CandidateScore,
    build_report,
    load_evaluation,
    select_operating_point,
)
from rebel_dot.evaluation.models import EvaluationCategory
from rebel_dot.ops.evaluate import (
    DEFAULT_BASELINE_PATH,
    baseline_violations,
    load_baseline,
    render_markdown,
)

BACKEND_ROOT = Path(__file__).parents[2]
DATASET_PATH = BACKEND_ROOT / "evaluation/datasets/support-routing-v1.json"
OBSERVATIONS_PATH = BACKEND_ROOT / "evaluation/observations/support-routing-v1.deterministic.json"
FAQ_PATH = BACKEND_ROOT / "data/faq.json"


def test_select_operating_point_prioritizes_local_precision_then_recall() -> None:
    cases = (
        CalibrationCase("strong-local", Route.LOCAL, (CandidateScore("faq-a", 0.87),)),
        CalibrationCase("boundary-local", Route.LOCAL, (CandidateScore("faq-b", 0.85),)),
        CalibrationCase("weak-fallback", Route.OPENAI, (CandidateScore("faq-c", 0.83),)),
        CalibrationCase(
            "near-neighbor",
            Route.OPENAI,
            (CandidateScore("faq-d", 0.88), CandidateScore("faq-e", 0.82)),
        ),
    )

    selected = select_operating_point(
        cases,
        similarity_thresholds=(0.82, 0.84, 0.86),
        similarity_margins=(0.05, 0.08),
    )

    assert selected.similarity_threshold == 0.84
    assert selected.similarity_margin == 0.08
    assert selected.local_precision == 1.0
    assert selected.local_recall == 1.0
    assert selected.false_local_count == 0


def test_versioned_evaluation_data_is_complete_and_separate() -> None:
    bundle = load_evaluation(DATASET_PATH, OBSERVATIONS_PATH, FAQ_PATH)

    assert bundle.dataset.dataset_version == "support-routing-v1"
    assert len(bundle.dataset.cases) == len(bundle.observations.cases) == 25
    assert {case.category for case in bundle.dataset.cases} == set(EvaluationCategory)


def test_report_selects_measured_operating_point_and_reports_quality() -> None:
    report = build_report(load_evaluation(DATASET_PATH, OBSERVATIONS_PATH, FAQ_PATH))

    assert report.observation_source == "deterministic_ci"
    assert report.selected_operating_point.similarity_threshold == 0.84
    assert report.selected_operating_point.similarity_margin == 0.08
    assert len(report.sweep) == 130
    assert report.retrieval.evaluated_cases == 11
    assert report.retrieval.recall_at_1 == pytest.approx(9 / 11, abs=1e-6)
    assert report.retrieval.recall_at_3 == 1.0
    assert report.retrieval.mean_reciprocal_rank == pytest.approx(10 / 11, abs=1e-6)
    assert report.routing.accuracy == 1.0
    assert report.routing.local_precision == 1.0
    assert report.routing.local_recall == 1.0
    assert report.routing.false_local_count == 0
    assert report.scope.accuracy == 1.0
    assert report.scope.in_domain_f1 == 1.0
    assert report.guardrails.attack_block_rate == 1.0
    assert report.guardrails.benign_false_positive_rate == 0.0
    assert report.schema_validity.valid_response_rate == 1.0
    assert report.latency.p50_ms == 49
    assert report.latency.p95_ms == 439
    assert report.usage_by_route["openai"].case_count == 9
    assert report.usage_by_route["openai"].input_tokens == 670
    assert report.usage_by_route["openai"].output_tokens == 915
    assert report.subjective_fallback.reviewed_answers == 9
    assert report.subjective_fallback.review_count == 18
    assert report.subjective_fallback.mean_correctness >= 4
    assert report.subjective_fallback.unsupported_claim_rate == 0
    assert {weak.case_id for weak in report.weak_cases} >= {
        "near-email-change",
        "near-two-factor",
        "near-account-removal",
        "faq-notification-settings",
        "fallback-wifi",
    }

    assert baseline_violations(report, load_baseline(DEFAULT_BASELINE_PATH)) == ()
    assert "Deterministic CI evidence only" in render_markdown(report)
