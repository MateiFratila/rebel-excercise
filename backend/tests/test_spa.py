from collections.abc import Sequence
from pathlib import Path

from fastapi.testclient import TestClient

from rebel_dot.api.app import create_app
from rebel_dot.core import Settings
from rebel_dot.domain import AnswerSource, QuestionAnswer

ARGON2_HASH = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA"


class FakeEmbeddingProvider:
    async def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return tuple((1.0, 0.0, 0.0) for _ in texts)


class FakeTaskDispatcher:
    async def dispatch_embedding_job(self, _job_id: object) -> None:
        return None


class FakeQuestionAnswerer:
    async def ask(self, _question: str) -> QuestionAnswer:
        return QuestionAnswer(AnswerSource.COMPLIANCE, None, "Unavailable")


def test_serves_spa_assets_and_fallback_without_shadowing_api(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    (tmp_path / "index.html").write_text("<main>Semantic FAQ</main>", encoding="utf-8")
    (tmp_path / "favicon.svg").write_text("<svg />", encoding="utf-8")
    (assets / "app.js").write_text("window.loaded = true", encoding="utf-8")
    settings = Settings(
        openai_api_key="sk-test-only",
        shared_password_hash=ARGON2_HASH,
    )
    client = TestClient(
        create_app(
            settings,
            embedding_provider=FakeEmbeddingProvider(),
            task_dispatcher=FakeTaskDispatcher(),
            question_answerer=FakeQuestionAnswerer(),
            static_directory=tmp_path,
        )
    )

    assert client.get("/").text == "<main>Semantic FAQ</main>"
    assert client.get("/knowledge").text == "<main>Semantic FAQ</main>"
    assert client.get("/favicon.svg").text == "<svg />"
    assert client.head("/favicon.svg").headers["content-type"] == "image/svg+xml"
    assert client.get("/assets/app.js").text == "window.loaded = true"
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/admin/not-a-route").status_code == 404
