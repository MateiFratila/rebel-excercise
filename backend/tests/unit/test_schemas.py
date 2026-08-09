import pytest
from pydantic import ValidationError

from rebel_dot.api.schemas import AskQuestionRequest, AskQuestionResponse, ErrorResponse
from rebel_dot.domain import AnswerSource, ErrorCode


def test_question_schema_rejects_unknown_fields_and_blank_input() -> None:
    with pytest.raises(ValidationError):
        AskQuestionRequest.model_validate({"user_question": " ", "unexpected": True})


def test_question_response_uses_stable_source_values() -> None:
    response = AskQuestionResponse(
        source=AnswerSource.LOCAL,
        matched_question="How do I reset my password?",
        answer="Open account settings.",
    )

    assert response.model_dump(mode="json")["source"] == "local"


def test_error_envelope_is_stable() -> None:
    response = ErrorResponse.model_validate(
        {
            "error": {
                "code": ErrorCode.NOT_FOUND,
                "message": "Resource not found.",
                "request_id": "request-123",
            }
        }
    )

    assert response.model_dump(mode="json") == {
        "error": {
            "code": "not_found",
            "message": "Resource not found.",
            "request_id": "request-123",
        }
    }
