import os
from collections.abc import Sequence

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError

from rebel_dot.adapters.db.database import create_database_engine
from rebel_dot.adapters.db.models import AuthSessionRecord
from rebel_dot.api.app import create_app
from rebel_dot.core import Environment, Settings
from rebel_dot.domain import (
    AIProviderError,
    AnswerSource,
    EmbeddingProviderError,
    GuardrailReason,
    GuardrailRejectedError,
    OutputRejectedError,
    ProviderFailureKind,
    QuestionAnswer,
)

pytestmark = pytest.mark.integration
ORIGIN = "https://support.example.test"
PASSWORD = "correct horse battery staple"


class FakeEmbeddingProvider:
    async def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return tuple((1.0, 0.0, 0.0) for _ in texts)


class FakeTaskDispatcher:
    async def dispatch_embedding_job(self, _job_id: object) -> None:
        return None


class StubQuestionAnswerer:
    def __init__(self) -> None:
        self.result: QuestionAnswer | Exception = QuestionAnswer(
            AnswerSource.LOCAL,
            "How can I restore my account settings?",
            "Go to settings and click on 'restore default'.",
        )
        self.calls: list[str] = []

    async def ask(self, question: str) -> QuestionAnswer:
        self.calls.append(question)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if value is None:
        pytest.skip("TEST_DATABASE_URL is required for question API integration tests")
    return value


@pytest.fixture
def settings(database_url: str) -> Settings:
    hasher = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1)
    return Settings(
        environment=Environment.TEST,
        database_url=database_url,
        openai_api_key="sk-test-only",
        shared_password_hash=hasher.hash(PASSWORD),
        embedding_dimensions=3,
        allowed_origins=(ORIGIN,),
        session_cookie_secure=True,
    )


@pytest.fixture(autouse=True)
async def clear_auth_sessions(database_url: str) -> None:
    engine = create_database_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(delete(AuthSessionRecord))
    yield
    async with engine.begin() as connection:
        await connection.execute(delete(AuthSessionRecord))
    await engine.dispose()


def test_question_api_contract_and_safe_error_mappings(
    settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    answerer = StubQuestionAnswerer()
    app = create_app(
        settings,
        embedding_provider=FakeEmbeddingProvider(),
        task_dispatcher=FakeTaskDispatcher(),
        question_answerer=answerer,
    )
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        unauthenticated = client.post(
            "/ask-question",
            headers={"Origin": ORIGIN},
            json={"user_question": "Help"},
        )
        assert unauthenticated.status_code == 401
        assert (
            client.post(
                "/auth/session",
                headers={"Origin": ORIGIN},
                json={"password": PASSWORD},
            ).status_code
            == 204
        )
        assert client.post("/ask-question", json={"user_question": "Help"}).status_code == 403

        raw_question = "private support question"
        success = client.post(
            "/ask-question",
            headers={"Origin": ORIGIN},
            json={"user_question": raw_question},
        )
        assert success.status_code == 200
        assert success.json() == {
            "source": "local",
            "matched_question": "How can I restore my account settings?",
            "answer": "Go to settings and click on 'restore default'.",
        }
        assert success.headers["x-request-id"]
        assert raw_question not in capsys.readouterr().out

        failures = (
            (GuardrailRejectedError(GuardrailReason.PROMPT_INJECTION), 422, "validation_error"),
            (OutputRejectedError(GuardrailReason.SECRET_LEAK), 502, "upstream_invalid_response"),
            (
                AIProviderError(ProviderFailureKind.INVALID_RESPONSE),
                502,
                "upstream_invalid_response",
            ),
            (AIProviderError(ProviderFailureKind.RATE_LIMITED), 429, "rate_limited"),
            (AIProviderError(ProviderFailureKind.TIMEOUT), 504, "upstream_timeout"),
            (AIProviderError(ProviderFailureKind.UNAVAILABLE), 503, "dependency_unavailable"),
            (EmbeddingProviderError("secret embedding detail"), 503, "dependency_unavailable"),
            (SQLAlchemyError("secret database detail"), 503, "dependency_unavailable"),
        )
        for error, expected_status, expected_code in failures:
            answerer.result = error
            failed = client.post(
                "/ask-question",
                headers={"Origin": ORIGIN},
                json={"user_question": "Help"},
            )
            assert failed.status_code == expected_status
            assert failed.json()["error"]["code"] == expected_code
            assert failed.headers["x-request-id"] == failed.json()["error"]["request_id"]
            assert "secret" not in failed.text

        answerer.result = RuntimeError("secret unexpected detail")
        unexpected = client.post(
            "/ask-question",
            headers={"Origin": ORIGIN},
            json={"user_question": "Help"},
        )
        assert unexpected.status_code == 500
        assert unexpected.json()["error"]["code"] == "internal_error"
        assert "secret unexpected detail" not in unexpected.text
