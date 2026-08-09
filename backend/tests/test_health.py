from fastapi.testclient import TestClient

from rebel_dot.api.app import create_app
from rebel_dot.core import Settings

ARGON2_HASH = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA"


def test_health_live() -> None:
    settings = Settings(
        openai_api_key="sk-test-only",
        shared_password_hash=ARGON2_HASH,
    )
    response = TestClient(create_app(settings)).get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
