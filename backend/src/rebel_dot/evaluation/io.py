from pathlib import Path

from rebel_dot.evaluation.models import EvaluationBundle, EvaluationDataset, ObservationSet
from rebel_dot.ops.faq_fixture import load_faq_fixture


def load_evaluation(
    dataset_path: Path,
    observations_path: Path,
    faq_path: Path,
) -> EvaluationBundle:
    dataset = EvaluationDataset.model_validate_json(dataset_path.read_text(encoding="utf-8"))
    observations = ObservationSet.model_validate_json(observations_path.read_text(encoding="utf-8"))
    if dataset.dataset_version != observations.dataset_version:
        raise ValueError("observation dataset version does not match the labeled dataset")

    case_ids = tuple(case.id for case in dataset.cases)
    observation_ids = tuple(observation.case_id for observation in observations.cases)
    _require_unique(case_ids, "dataset case")
    _require_unique(observation_ids, "observation case")
    if set(case_ids) != set(observation_ids):
        raise ValueError("every labeled case must have exactly one observation")

    fixture = load_faq_fixture(faq_path)
    canonical_questions = {item.question for item in fixture.knowledge_base_items}
    if dataset.collection.record_count != len(fixture.knowledge_base_items):
        raise ValueError("dataset collection record count does not match the FAQ fixture")
    if any(case.question in canonical_questions for case in dataset.cases):
        raise ValueError("evaluation questions must be separate from canonical FAQ questions")
    if any(
        case.expected_question is not None and case.expected_question not in canonical_questions
        for case in dataset.cases
    ):
        raise ValueError("expected FAQ questions must exist in the canonical fixture")
    if any(
        candidate.question not in canonical_questions
        for observation in observations.cases
        for candidate in observation.candidates
    ):
        raise ValueError("observed candidates must exist in the canonical fixture")

    return EvaluationBundle(dataset, observations, dataset_path, observations_path)


def _require_unique(values: tuple[str, ...], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} IDs must be unique")
