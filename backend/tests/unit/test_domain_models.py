from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from rebel_dot.domain import (
    AnswerSource,
    CollectionStatus,
    FAQCollection,
    ScopeDecision,
    WorkflowState,
)


def test_public_enum_values_match_transport_and_persistence_contracts() -> None:
    assert [source.value for source in AnswerSource] == ["local", "openai", "compliance"]
    assert ScopeDecision.UNCERTAIN.value == "uncertain"
    assert CollectionStatus.ACTIVE.value == "active"


def test_domain_entities_are_immutable() -> None:
    now = datetime.now(UTC)
    collection = FAQCollection(
        id=uuid4(),
        name="support",
        version=1,
        status=CollectionStatus.DRAFT,
        embedding_model="text-embedding-3-small",
        embedding_dimensions=1536,
        created_at=now,
        updated_at=now,
    )

    with pytest.raises(FrozenInstanceError):
        collection.version = 2  # type: ignore[misc]


def test_workflow_state_has_no_shared_mutable_defaults() -> None:
    first = WorkflowState(raw_question="First")
    second = WorkflowState(raw_question="Second")

    assert first.candidates == ()
    assert first.diagnostics == second.diagnostics == {}
    assert first.diagnostics is not second.diagnostics
