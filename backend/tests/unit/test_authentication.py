import base64
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self, cast
from uuid import uuid4

import pytest
from argon2 import PasswordHasher

from rebel_dot.application.authentication import (
    InvalidCredentialsError,
    LoginRateLimiter,
    SessionService,
    digest_session_token,
    generate_session_token,
)
from rebel_dot.domain import AuthSession
from rebel_dot.ports import UnitOfWork

PASSWORD = "correct horse battery staple"


@dataclass
class MutableClock:
    current: datetime

    def __call__(self) -> datetime:
        return self.current


class InMemorySessionRepository:
    def __init__(self) -> None:
        self.records: dict[str, AuthSession] = {}

    async def add(self, session: AuthSession) -> None:
        self.records[session.token_digest] = session

    async def get_by_digest(self, token_digest: str, now: datetime) -> AuthSession | None:
        session = self.records.get(token_digest)
        if session is None or session.expires_at <= now or session.revoked_at is not None:
            return None
        resolved = replace(session, last_seen_at=now)
        self.records[token_digest] = resolved
        return resolved

    async def revoke(self, token_digest: str, revoked_at: datetime) -> bool:
        session = self.records.get(token_digest)
        if session is None or session.revoked_at is not None:
            return False
        self.records[token_digest] = replace(session, revoked_at=revoked_at)
        return True

    async def prune_expired(self, now: datetime) -> int:
        expired = [
            token_digest
            for token_digest, session in self.records.items()
            if session.expires_at <= now
        ]
        for token_digest in expired:
            del self.records[token_digest]
        return len(expired)


class FakeUnitOfWork:
    def __init__(self, sessions: InMemorySessionRepository) -> None:
        self.sessions = sessions

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


def make_service(
    sessions: InMemorySessionRepository,
    clock: MutableClock,
    tokens: list[str],
) -> SessionService:
    hasher = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1)
    password_hash = hasher.hash(PASSWORD)
    token_iterator = iter(tokens)
    unit_of_work_factory = cast(
        Callable[[], UnitOfWork],
        lambda: FakeUnitOfWork(sessions),
    )
    return SessionService(
        password_hash=password_hash,
        session_lifetime_seconds=604800,
        unit_of_work_factory=unit_of_work_factory,
        rate_limiter=LoginRateLimiter(limit=5, window_seconds=60),
        password_hasher=hasher,
        clock=clock,
        token_factory=lambda: next(token_iterator),
    )


def test_generated_session_token_contains_256_bits_and_digest_is_stable() -> None:
    token = generate_session_token()
    decoded = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))

    assert len(decoded) == 32
    assert len(digest_session_token(token)) == 64
    assert digest_session_token(token) == digest_session_token(token)


async def test_session_lifecycle_stores_only_digest_and_does_not_slide_expiry() -> None:
    now = datetime(2026, 8, 9, 12, tzinfo=UTC)
    clock = MutableClock(now)
    sessions = InMemorySessionRepository()
    sessions.records["expired"] = AuthSession(
        id=uuid4(),
        token_digest="expired",
        expires_at=now,
        created_at=now - timedelta(days=8),
        revoked_at=None,
        last_seen_at=None,
    )
    service = make_service(sessions, clock, ["first-token", "second-token"])

    first = await service.create_session(PASSWORD, "192.0.2.1")
    second = await service.create_session(PASSWORD, "192.0.2.1")

    assert first.token == "first-token"
    assert second.token == "second-token"
    assert first.expires_at == now + timedelta(days=7)
    assert "expired" not in sessions.records
    assert set(sessions.records) == {
        digest_session_token("first-token"),
        digest_session_token("second-token"),
    }
    assert PASSWORD not in repr(tuple(sessions.records.values()))
    assert "first-token" not in repr(tuple(sessions.records.values()))

    clock.current += timedelta(days=1)
    resolved = await service.resolve_session("first-token")
    assert resolved is not None
    assert resolved.last_seen_at == clock.current
    assert resolved.expires_at == first.expires_at

    assert await service.revoke_session("first-token")
    assert not await service.revoke_session("first-token")
    assert await service.resolve_session("first-token") is None


async def test_invalid_password_has_generic_failure_and_creates_no_session() -> None:
    sessions = InMemorySessionRepository()
    service = make_service(
        sessions,
        MutableClock(datetime(2026, 8, 9, 12, tzinfo=UTC)),
        ["unused-token"],
    )

    with pytest.raises(InvalidCredentialsError):
        await service.create_session("wrong password", "192.0.2.1")

    assert sessions.records == {}


def test_login_rate_limiter_is_per_client_and_refills_over_time() -> None:
    current = 0.0
    limiter = LoginRateLimiter(limit=2, window_seconds=10, clock=lambda: current)

    assert limiter.consume("192.0.2.1")
    assert limiter.consume("192.0.2.1")
    assert not limiter.consume("192.0.2.1")
    assert limiter.consume("198.51.100.2")

    current = 5.0
    assert limiter.consume("192.0.2.1")
