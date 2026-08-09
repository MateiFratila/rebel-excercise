import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Annotated

import pytest
from argon2 import PasswordHasher
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update

from rebel_dot.adapters.db.database import create_database_engine, create_session_factory
from rebel_dot.adapters.db.models import AuthSessionRecord
from rebel_dot.api.app import create_app
from rebel_dot.api.authentication import get_session
from rebel_dot.application.authentication import digest_session_token
from rebel_dot.core import Environment, Settings
from rebel_dot.domain import AuthSession

pytestmark = pytest.mark.integration
ORIGIN = "https://support.example.test"
PASSWORD = "correct horse battery staple"


@pytest.fixture
def database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if value is None:
        pytest.skip("TEST_DATABASE_URL is required for authentication integration tests")
    return value


@pytest.fixture
def settings(database_url: str) -> Settings:
    hasher = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1)
    return Settings(
        environment=Environment.TEST,
        database_url=database_url,
        openai_api_key="sk-test-only",
        shared_password_hash=hasher.hash(PASSWORD),
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


async def test_session_http_lifecycle_and_credential_containment(
    settings: Settings,
    database_url: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app(settings)

    @app.get("/protected")
    async def protected(
        _session: Annotated[AuthSession, Depends(get_session)],
    ) -> dict[str, bool]:
        return {"authenticated": True}

    caplog.set_level(logging.DEBUG)
    with TestClient(app, base_url=ORIGIN) as client:
        unauthenticated = client.get("/protected")
        assert unauthenticated.status_code == 401

        login = client.post(
            "/auth/session",
            headers={"Origin": ORIGIN},
            json={"password": PASSWORD},
        )
        assert login.status_code == 204
        assert login.content == b""
        set_cookie = login.headers["set-cookie"]
        assert "Max-Age=604800" in set_cookie
        assert "Path=/" in set_cookie
        assert "Secure" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "SameSite=strict" in set_cookie

        first_token = client.cookies.get(settings.session_cookie_name)
        assert first_token is not None
        assert client.get("/auth/session").status_code == 204
        assert client.get("/protected").json() == {"authenticated": True}

        second_login = client.post(
            "/auth/session",
            headers={"Origin": ORIGIN},
            json={"password": PASSWORD},
        )
        assert second_login.status_code == 204
        second_token = client.cookies.get(settings.session_cookie_name)
        assert second_token is not None and second_token != first_token

        rejected_logout = client.delete(
            "/auth/session",
            headers={"Origin": "https://evil.example"},
        )
        assert rejected_logout.status_code == 403
        assert client.get("/auth/session").status_code == 204

        logout = client.delete("/auth/session", headers={"Origin": ORIGIN})
        assert logout.status_code == 204
        assert "Max-Age=0" in logout.headers["set-cookie"]
        assert client.delete("/auth/session", headers={"Origin": ORIGIN}).status_code == 204

        rejected = client.get("/auth/session")
        assert rejected.status_code == 401
        assert rejected.json()["error"]["code"] == "authentication_required"
        assert rejected.headers["x-request-id"] == rejected.json()["error"]["request_id"]

    engine = create_database_engine(database_url)
    session_factory = create_session_factory(engine)
    async with session_factory() as database_session:
        records = tuple(await database_session.scalars(select(AuthSessionRecord)))
    await engine.dispose()

    assert len(records) == 2
    assert {record.token_digest for record in records} == {
        digest_session_token(first_token),
        digest_session_token(second_token),
    }
    records_by_digest = {record.token_digest: record for record in records}
    assert records_by_digest[digest_session_token(first_token)].revoked_at is None
    assert records_by_digest[digest_session_token(second_token)].revoked_at is not None
    assert all(record.token_digest not in {first_token, second_token} for record in records)
    assert PASSWORD not in caplog.text
    assert first_token not in caplog.text
    assert second_token not in caplog.text


async def test_login_rejects_untrusted_origins_and_throttles_generic_failures(
    settings: Settings,
) -> None:
    limited_settings = settings.model_copy(
        update={"login_rate_limit": 2, "login_rate_window_seconds": 60}
    )
    with TestClient(create_app(limited_settings), base_url=ORIGIN) as client:
        missing_origin = client.post("/auth/session", json={"password": PASSWORD})
        untrusted_origin = client.post(
            "/auth/session",
            headers={"Origin": "https://evil.example"},
            json={"password": PASSWORD},
        )
        assert missing_origin.status_code == 403
        assert untrusted_origin.status_code == 403
        assert missing_origin.json()["error"]["code"] == "forbidden"

        first = client.post(
            "/auth/session",
            headers={"Origin": ORIGIN},
            json={"password": "wrong-password"},
        )
        second = client.post(
            "/auth/session",
            headers={"Origin": ORIGIN},
            json={"password": "still-wrong"},
        )
        throttled = client.post(
            "/auth/session",
            headers={"Origin": ORIGIN},
            json={"password": PASSWORD},
        )

        assert first.status_code == second.status_code == 401
        assert first.json()["error"]["message"] == "Authentication failed"
        assert second.json()["error"]["message"] == "Authentication failed"
        assert throttled.status_code == 429
        assert throttled.headers["retry-after"] == "60"
        assert throttled.json()["error"]["code"] == "rate_limited"


async def test_expired_session_is_rejected(settings: Settings, database_url: str) -> None:
    with TestClient(create_app(settings), base_url=ORIGIN) as client:
        assert (
            client.post(
                "/auth/session",
                headers={"Origin": ORIGIN},
                json={"password": PASSWORD},
            ).status_code
            == 204
        )
        token = client.cookies.get(settings.session_cookie_name)
        assert token is not None

        now = datetime.now(UTC)
        engine = create_database_engine(database_url)
        async with engine.begin() as connection:
            await connection.execute(
                update(AuthSessionRecord)
                .where(AuthSessionRecord.token_digest == digest_session_token(token))
                .values(
                    created_at=now - timedelta(days=8),
                    expires_at=now - timedelta(days=1),
                )
            )
        await engine.dispose()

        assert client.get("/auth/session").status_code == 401
