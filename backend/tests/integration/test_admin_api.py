import os
from collections.abc import Sequence

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import delete

from rebel_dot.adapters.db.database import create_database_engine
from rebel_dot.adapters.db.models import (
    AuthSessionRecord,
    EmbeddingJobRecord,
    FAQCollectionRecord,
    FAQItemRecord,
)
from rebel_dot.api.app import create_app
from rebel_dot.core import Environment, Settings

pytestmark = pytest.mark.integration
ORIGIN = "https://support.example.test"
PASSWORD = "correct horse battery staple"


class DeterministicEmbeddingProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    async def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        batch = tuple(texts)
        self.calls.append(batch)
        return tuple(self._vector(text) for text in batch)

    @staticmethod
    def _vector(text: str) -> tuple[float, ...]:
        if "password" in text.casefold():
            return (1.0, 0.0, 0.0)
        return (0.0, 1.0, 0.0)


@pytest.fixture
def database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if value is None:
        pytest.skip("TEST_DATABASE_URL is required for administration integration tests")
    return value


@pytest.fixture
def settings(database_url: str) -> Settings:
    hasher = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1)
    return Settings(
        environment=Environment.TEST,
        database_url=database_url,
        openai_api_key="sk-test-only",
        shared_password_hash=hasher.hash(PASSWORD),
        embedding_model="text-embedding-3-small",
        embedding_dimensions=3,
        embedding_batch_size=2,
        job_poll_interval_seconds=0.01,
        allowed_origins=(ORIGIN,),
        session_cookie_secure=True,
    )


@pytest.fixture(autouse=True)
async def clear_database(database_url: str) -> None:
    engine = create_database_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(delete(EmbeddingJobRecord))
        await connection.execute(delete(FAQItemRecord))
        await connection.execute(delete(FAQCollectionRecord))
        await connection.execute(delete(AuthSessionRecord))
    yield
    async with engine.begin() as connection:
        await connection.execute(delete(EmbeddingJobRecord))
        await connection.execute(delete(FAQItemRecord))
        await connection.execute(delete(FAQCollectionRecord))
        await connection.execute(delete(AuthSessionRecord))
    await engine.dispose()


def wait_for_job(
    client: TestClient,
    location: str,
) -> dict[str, object]:
    body: dict[str, object] = {}
    for _ in range(100):
        response = client.get(location)
        assert response.status_code == 200
        body = response.json()
        if body["status"] in {"completed", "partially_failed", "failed"}:
            return body
    raise AssertionError(f"embedding job did not finish: {body}")


def test_authenticated_administration_workflow(
    settings: Settings,
) -> None:
    provider = DeterministicEmbeddingProvider()
    app = create_app(settings, embedding_provider=provider)
    with TestClient(
        app,
        base_url=ORIGIN,
    ) as client:
        assert client.get("/admin/collections").status_code == 401
        assert client.get("/health/ready").status_code == 503
        assert (
            client.post(
                "/auth/session",
                headers={"Origin": ORIGIN},
                json={"password": PASSWORD},
            ).status_code
            == 204
        )

        created = client.post(
            "/admin/collections",
            headers={"Origin": ORIGIN},
            json={
                "name": "support",
                "embedding_model": "text-embedding-3-small",
                "embedding_dimensions": 3,
            },
        )
        assert created.status_code == 201
        collection = created.json()
        collection_id = collection["id"]
        assert collection["version"] == 1
        assert collection["readiness"] == {
            "ready": False,
            "active_items": 0,
            "pending_items": 0,
        }

        incompatible = client.post(
            "/admin/collections",
            headers={"Origin": ORIGIN},
            json={
                "name": "incompatible",
                "embedding_model": "text-embedding-3-large",
                "embedding_dimensions": 3,
            },
        )
        assert incompatible.status_code == 409

        payload = {
            "items": [
                {
                    "question": "How do I reset my password?",
                    "answer": "Use the reset form.",
                    "category": "security",
                    "source_metadata": {"source": "test"},
                },
                {
                    "question": "How do I change my email?",
                    "answer": "Open account settings.",
                    "category": "profile",
                    "source_metadata": {},
                },
            ]
        }
        items_url = f"/admin/collections/{collection_id}/items"
        imported = client.post(items_url, headers={"Origin": ORIGIN}, json=payload)
        assert imported.status_code == 200
        assert imported.json() == {"changed_count": 2}
        assert client.post(items_url, headers={"Origin": ORIGIN}, json=payload).json() == {
            "changed_count": 0
        }
        assert provider.calls == []

        blocked_activation = client.post(
            f"/admin/collections/{collection_id}/activate",
            headers={"Origin": ORIGIN},
        )
        assert blocked_activation.status_code == 409

        queued = client.post(
            f"/admin/collections/{collection_id}/embedding-jobs",
            headers={"Origin": ORIGIN},
        )
        assert queued.status_code == 202
        assert queued.json()["status"] == "queued"
        assert queued.headers["location"] == f"/admin/jobs/{queued.json()['job_id']}"
        completed = wait_for_job(
            client,
            queued.headers["location"],
        )
        assert completed["status"] == "completed"
        assert completed["processed_count"] == 2
        assert len(provider.calls) == 1

        activated = client.post(
            f"/admin/collections/{collection_id}/activate",
            headers={"Origin": ORIGIN},
        )
        assert activated.status_code == 200
        assert activated.json()["status"] == "active"
        assert activated.json()["readiness"]["ready"] is True
        assert client.get("/health/ready").json() == {"status": "ok"}

        items = client.get(items_url).json()
        password_item = next(item for item in items if "password" in item["question"])
        update_payload = {
            "question": password_item["question"],
            "answer": "Use the secure reset form.",
            "category": password_item["category"],
            "source_metadata": password_item["source_metadata"],
            "expected_updated_at": password_item["updated_at"],
        }
        item_url = f"{items_url}/{password_item['id']}"
        updated = client.patch(item_url, headers={"Origin": ORIGIN}, json=update_payload)
        assert updated.status_code == 200
        assert updated.json()["embedding_model"] is None
        assert (
            client.patch(
                item_url,
                headers={"Origin": ORIGIN},
                json=update_payload,
            ).status_code
            == 409
        )

        previous_call_count = len(provider.calls)
        incremental = client.post(
            f"/admin/collections/{collection_id}/embedding-jobs",
            headers={"Origin": ORIGIN},
        )
        assert (
            wait_for_job(
                client,
                incremental.headers["location"],
            )["processed_count"]
            == 1
        )
        assert len(provider.calls) == previous_call_count + 1

        no_op = client.post(
            f"/admin/collections/{collection_id}/embedding-jobs",
            headers={"Origin": ORIGIN},
        )
        assert no_op.status_code == 202
        assert no_op.json()["status"] == "completed"
        assert len(provider.calls) == previous_call_count + 1

        rejected_delete = client.delete(item_url)
        assert rejected_delete.status_code == 403
        deactivated = client.delete(item_url, headers={"Origin": ORIGIN})
        assert deactivated.status_code == 200
        assert deactivated.json()["is_active"] is False


def test_admin_validation_errors_do_not_echo_input(settings: Settings) -> None:
    with TestClient(create_app(settings), base_url=ORIGIN) as client:
        secret_value = "do-not-echo-this-value"
        response = client.post(
            "/auth/session",
            headers={"Origin": ORIGIN},
            json={"password": secret_value, "unexpected": True},
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"
        assert secret_value not in response.text
