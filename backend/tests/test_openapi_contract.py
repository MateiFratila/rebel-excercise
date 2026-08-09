import hashlib
import json
from collections.abc import Sequence

from rebel_dot.api.app import create_app
from rebel_dot.core import Settings
from rebel_dot.domain import AnswerSource, QuestionAnswer

ARGON2_HASH = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA"
OPENAPI_SHA256 = "2d7f3493fd0b4566ce03e5e202752f836cfc873b54fffb1316f10ed0788437ad"


class FakeEmbeddingProvider:
    async def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return tuple((1.0, 0.0, 0.0) for _ in texts)


class FakeTaskDispatcher:
    async def dispatch_embedding_job(self, _job_id: object) -> None:
        return None


class FakeQuestionAnswerer:
    async def ask(self, _question: str) -> QuestionAnswer:
        return QuestionAnswer(AnswerSource.COMPLIANCE, None, "Unavailable")


def test_openapi_contract_is_frozen() -> None:
    settings = Settings(
        openai_api_key="sk-test-only",
        shared_password_hash=ARGON2_HASH,
    )
    app = create_app(
        settings,
        embedding_provider=FakeEmbeddingProvider(),
        task_dispatcher=FakeTaskDispatcher(),
        question_answerer=FakeQuestionAnswerer(),
    )

    serialized = json.dumps(app.openapi(), sort_keys=True, separators=(",", ":"))

    assert hashlib.sha256(serialized.encode()).hexdigest() == OPENAPI_SHA256
