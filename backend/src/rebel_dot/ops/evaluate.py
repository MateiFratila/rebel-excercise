import argparse
from collections.abc import Sequence
from pathlib import Path

from pydantic import Field

from rebel_dot.evaluation import EvaluationReport, build_report, load_evaluation
from rebel_dot.evaluation.models import StrictModel

BACKEND_ROOT = Path(__file__).parents[3]
DEFAULT_DATASET_PATH = BACKEND_ROOT / "evaluation/datasets/support-routing-v1.json"
DEFAULT_OBSERVATIONS_PATH = (
    BACKEND_ROOT / "evaluation/observations/support-routing-v1.deterministic.json"
)
DEFAULT_FAQ_PATH = BACKEND_ROOT / "data/faq.json"
DEFAULT_BASELINE_PATH = BACKEND_ROOT / "evaluation/baselines/support-routing-v1.json"
DEFAULT_JSON_REPORT_PATH = BACKEND_ROOT / "evaluation/reports/support-routing-v1.deterministic.json"
DEFAULT_MARKDOWN_REPORT_PATH = (
    BACKEND_ROOT / "evaluation/reports/support-routing-v1.deterministic.md"
)


class EvaluationBaseline(StrictModel):
    dataset_version: str
    observation_version: str
    observation_source: str
    similarity_threshold: float = Field(ge=0, le=1)
    similarity_margin: float = Field(ge=0, le=1)
    scope_confidence_threshold: float = Field(ge=0, le=1)
    minimum_recall_at_1: float = Field(ge=0, le=1)
    minimum_recall_at_3: float = Field(ge=0, le=1)
    minimum_mean_reciprocal_rank: float = Field(ge=0, le=1)
    minimum_route_accuracy: float = Field(ge=0, le=1)
    minimum_local_precision: float = Field(ge=0, le=1)
    minimum_local_recall: float = Field(ge=0, le=1)
    maximum_false_local_count: int = Field(ge=0)
    minimum_scope_accuracy: float = Field(ge=0, le=1)
    minimum_attack_block_rate: float = Field(ge=0, le=1)
    maximum_benign_false_positive_rate: float = Field(ge=0, le=1)
    minimum_schema_valid_rate: float = Field(ge=0, le=1)
    minimum_subjective_correctness: float = Field(ge=1, le=5)
    maximum_unsupported_claim_rate: float = Field(ge=0, le=1)


def load_baseline(path: Path) -> EvaluationBaseline:
    return EvaluationBaseline.model_validate_json(path.read_text(encoding="utf-8"))


def baseline_violations(
    report: EvaluationReport,
    baseline: EvaluationBaseline,
) -> tuple[str, ...]:
    checks = (
        (report.dataset_version == baseline.dataset_version, "dataset version changed"),
        (
            report.observation_version == baseline.observation_version,
            "observation version changed",
        ),
        (
            report.observation_source == baseline.observation_source,
            "observation source changed",
        ),
        (
            report.selected_operating_point.similarity_threshold == baseline.similarity_threshold,
            "selected similarity threshold changed",
        ),
        (
            report.selected_operating_point.similarity_margin == baseline.similarity_margin,
            "selected similarity margin changed",
        ),
        (
            report.scope_confidence_threshold == baseline.scope_confidence_threshold,
            "scope confidence threshold changed",
        ),
        (
            report.retrieval.recall_at_1 >= baseline.minimum_recall_at_1,
            "Recall@1 regressed",
        ),
        (
            report.retrieval.recall_at_3 >= baseline.minimum_recall_at_3,
            "Recall@3 regressed",
        ),
        (
            report.retrieval.mean_reciprocal_rank >= baseline.minimum_mean_reciprocal_rank,
            "mean reciprocal rank regressed",
        ),
        (
            report.routing.accuracy >= baseline.minimum_route_accuracy,
            "route accuracy regressed",
        ),
        (
            report.routing.local_precision >= baseline.minimum_local_precision,
            "local precision regressed",
        ),
        (
            report.routing.local_recall >= baseline.minimum_local_recall,
            "local recall regressed",
        ),
        (
            report.routing.false_local_count <= baseline.maximum_false_local_count,
            "false-local count regressed",
        ),
        (
            report.scope.accuracy >= baseline.minimum_scope_accuracy,
            "scope accuracy regressed",
        ),
        (
            report.guardrails.attack_block_rate >= baseline.minimum_attack_block_rate,
            "attack block rate regressed",
        ),
        (
            report.guardrails.benign_false_positive_rate
            <= baseline.maximum_benign_false_positive_rate,
            "benign guardrail false-positive rate regressed",
        ),
        (
            report.schema_validity.valid_response_rate >= baseline.minimum_schema_valid_rate,
            "schema-valid response rate regressed",
        ),
        (
            report.subjective_fallback.mean_correctness >= baseline.minimum_subjective_correctness,
            "subjective correctness regressed",
        ),
        (
            report.subjective_fallback.unsupported_claim_rate
            <= baseline.maximum_unsupported_claim_rate,
            "unsupported-claim rate regressed",
        ),
    )
    return tuple(message for passed, message in checks if not passed)


def render_json(report: EvaluationReport) -> str:
    return f"{report.model_dump_json(indent=2)}\n"


def render_markdown(report: EvaluationReport) -> str:
    point = report.selected_operating_point
    lines = [
        f"# Evaluation Report: {report.dataset_version}",
        "",
        "> Deterministic CI evidence only. These observations are not live OpenAI measurements.",
        "",
        "## Evidence",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Observation version | `{report.observation_version}` |",
        f"| Captured at | `{report.captured_at}` |",
        f"| Source | `{report.observation_source}` |",
        f"| Taxonomy | `{report.taxonomy_version}` |",
        f"| Collection | `{report.collection['name']}@{report.collection['version']}` |",
        "",
        "## Selected Operating Point",
        "",
        "| Setting | Value |",
        "| --- | ---: |",
        f"| Similarity threshold | {point.similarity_threshold:.2f} |",
        f"| Similarity margin | {point.similarity_margin:.2f} |",
        f"| Scope confidence threshold | {report.scope_confidence_threshold:.2f} |",
        "",
        "## Objective Metrics",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Retrieval Recall@1 | {report.retrieval.recall_at_1:.6f} |",
        f"| Retrieval Recall@3 | {report.retrieval.recall_at_3:.6f} |",
        f"| Retrieval MRR | {report.retrieval.mean_reciprocal_rank:.6f} |",
        f"| Route accuracy | {report.routing.accuracy:.6f} |",
        f"| Local precision | {report.routing.local_precision:.6f} |",
        f"| Local recall | {report.routing.local_recall:.6f} |",
        f"| False-local count | {report.routing.false_local_count} |",
        f"| False-local rate | {report.routing.false_local_rate:.6f} |",
        f"| Scope accuracy | {report.scope.accuracy:.6f} |",
        f"| Scope in-domain F1 | {report.scope.in_domain_f1:.6f} |",
        f"| Attack block rate | {report.guardrails.attack_block_rate:.6f} |",
        (
            "| Benign guardrail false-positive rate | "
            f"{report.guardrails.benign_false_positive_rate:.6f} |"
        ),
        f"| Schema-valid response rate | {report.schema_validity.valid_response_rate:.6f} |",
        f"| Latency p50 | {report.latency.p50_ms:.0f} ms |",
        f"| Latency p95 | {report.latency.p95_ms:.0f} ms |",
        "",
        "## Usage by Route",
        "",
        "| Route | Cases | Input tokens | Output tokens | Estimated cost (USD) |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    lines.extend(
        (
            f"| {route} | {usage.case_count} | {usage.input_tokens} | "
            f"{usage.output_tokens} | {usage.estimated_cost_usd:.8f} |"
        )
        for route, usage in report.usage_by_route.items()
    )
    subjective = report.subjective_fallback
    lines.extend(
        (
            "",
            "## Subjective Fallback Review",
            "",
            f"- Reviewed answers: {subjective.reviewed_answers}",
            f"- Reviews: {subjective.review_count}",
            f"- Mean relevance: {subjective.mean_relevance:.6f}",
            f"- Mean correctness: {subjective.mean_correctness:.6f}",
            f"- Mean clarity: {subjective.mean_clarity:.6f}",
            f"- Mean safety: {subjective.mean_safety:.6f}",
            f"- Mean consistency: {subjective.mean_consistency:.6f}",
            f"- Unsupported-claim rate: {subjective.unsupported_claim_rate:.6f}",
            "",
            "## Known Weak Cases",
            "",
        )
    )
    lines.extend(f"- `{case.case_id}`: {case.reason}" for case in report.weak_cases)
    lines.extend(("", "## Limitations", ""))
    lines.extend(f"- {limitation}" for limitation in report.limitations)
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = build_report(load_evaluation(args.dataset, args.observations, args.faq))
    json_report = render_json(report)
    markdown_report = render_markdown(report)
    baseline = load_baseline(args.baseline)
    violations = list(baseline_violations(report, baseline))

    if args.write:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(json_report, encoding="utf-8")
        args.markdown_report.write_text(markdown_report, encoding="utf-8")
        print(f"Wrote {args.json_report}")
        print(f"Wrote {args.markdown_report}")
    elif args.check:
        violations.extend(_artifact_violations(args.json_report, json_report, "JSON"))
        violations.extend(_artifact_violations(args.markdown_report, markdown_report, "Markdown"))
    else:
        print(markdown_report, end="")

    if violations:
        for violation in violations:
            print(f"evaluation check failed: {violation}")
        return 1
    print(
        "Evaluation passed at "
        f"threshold={report.selected_operating_point.similarity_threshold:.2f}, "
        f"margin={report.selected_operating_point.similarity_margin:.2f}."
    )
    return 0


def _artifact_violations(path: Path, expected: str, label: str) -> tuple[str, ...]:
    if not path.is_file():
        return (f"{label} report is missing: {path}",)
    if path.read_text(encoding="utf-8") != expected:
        return (f"{label} report is stale; run with --write",)
    return ()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and verify the support evaluation report")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="write deterministic report artifacts")
    mode.add_argument("--check", action="store_true", help="check baselines and report artifacts")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--observations", type=Path, default=DEFAULT_OBSERVATIONS_PATH)
    parser.add_argument("--faq", type=Path, default=DEFAULT_FAQ_PATH)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE_PATH)
    parser.add_argument("--json-report", type=Path, default=DEFAULT_JSON_REPORT_PATH)
    parser.add_argument("--markdown-report", type=Path, default=DEFAULT_MARKDOWN_REPORT_PATH)
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
