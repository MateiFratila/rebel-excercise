import json
import logging
from typing import Any

from fastapi.testclient import TestClient

from rebel_dot.api.app import create_app
from rebel_dot.api.authentication import get_session, require_allowed_origin
from rebel_dot.core import Settings
from rebel_dot.core.observability import (
    REDACTED,
    configure_observability,
    logger,
    redact_sensitive,
)
from rebel_dot.domain import AnswerSource, QuestionAnswer

ARGON2_HASH = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA"


class FakeEmbeddingProvider:
    async def embed(self, _texts: object) -> tuple[()]:
        return ()


class FakeTaskDispatcher:
    async def dispatch_embedding_job(self, _job_id: object) -> None:
        return None


class FakeQuestionAnswerer:
    async def ask(self, _question: str) -> QuestionAnswer:
        return QuestionAnswer(
            AnswerSource.LOCAL,
            "Canonical question",
            "Canonical answer",
            top_similarity=0.91,
            collection_version=4,
            embedding_model="text-embedding-3-small",
        )


def test_redaction_removes_sensitive_values_recursively() -> None:
    event: dict[str, Any] = {
        "event": "test",
        "password": "magicword",
        "nested": {
            "session_token": "opaque-token",
            "user_question": "private question",
            "safe": "visible",
        },
        "items": [{"answer": "private answer", "count": 2}],
    }

    redacted = redact_sensitive(None, "info", event)

    assert redacted["password"] == REDACTED
    assert redacted["nested"] == {
        "session_token": REDACTED,
        "user_question": REDACTED,
        "safe": "visible",
    }
    assert redacted["items"] == [{"answer": REDACTED, "count": 2}]
    assert "magicword" not in str(redacted)
    assert "opaque-token" not in str(redacted)
    assert "private question" not in str(redacted)
    assert "private answer" not in str(redacted)


def test_metrics_and_errors_use_safe_request_observability() -> None:
    settings = Settings(
        _env_file=None,
        openai_api_key="sk-test-only",
        shared_password_hash=ARGON2_HASH,
    )
    app = create_app(
        settings,
        embedding_provider=FakeEmbeddingProvider(),
        task_dispatcher=FakeTaskDispatcher(),
        question_answerer=FakeQuestionAnswerer(),
    )

    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        unauthenticated = client.get("/auth/session")
        metrics = client.get("/metrics")

    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["x-request-id"] == unauthenticated.json()["error"]["request_id"]
    assert metrics.status_code == 200
    assert "rebel_dot_http_requests_total" in metrics.text
    assert "rebel_dot_auth_events_total" in metrics.text
    assert "rebel_dot_auth_active_sessions" in metrics.text
    assert "rebel_dot_provider_tokens_total" in metrics.text
    assert "rebel_dot_embedding_jobs_total" in metrics.text


def test_structured_logs_are_json_and_redacted(caplog: Any) -> None:
    configure_observability("INFO")
    caplog.set_level(logging.INFO)

    logger.info(
        "redaction_test",
        password="magicword",
        session_token="opaque-token",
        safe_count=2,
    )

    event = json.loads(caplog.records[-1].getMessage())
    assert event["event"] == "redaction_test"
    assert event["level"] == "info"
    assert event["timestamp"]
    assert event["password"] == REDACTED
    assert event["session_token"] == REDACTED
    assert event["safe_count"] == 2
    assert "magicword" not in caplog.text
    assert "opaque-token" not in caplog.text


def test_question_log_includes_safe_collection_and_model_versions(caplog: Any) -> None:
    settings = Settings(
        _env_file=None,
        openai_api_key="sk-test-only",
        shared_password_hash=ARGON2_HASH,
    )
    app = create_app(
        settings,
        embedding_provider=FakeEmbeddingProvider(),
        task_dispatcher=FakeTaskDispatcher(),
        question_answerer=FakeQuestionAnswerer(),
    )
    app.dependency_overrides[get_session] = lambda: object()
    app.dependency_overrides[require_allowed_origin] = lambda: None
    caplog.set_level(logging.INFO)

    with TestClient(app) as client:
        response = client.post("/ask-question", json={"user_question": "private input"})

    assert response.status_code == 200
    events = (json.loads(record.getMessage()) for record in caplog.records)
    event = next(event for event in events if event.get("event") == "question_answered")
    assert event["collection_version"] == 4
    assert event["embedding_model"] == "text-embedding-3-small"
    assert event["chat_model"] == "gpt-5.4-mini"
    assert "private input" not in caplog.text
    assert "Canonical answer" not in caplog.text
