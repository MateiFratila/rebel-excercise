import asyncio
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import Lock
from time import monotonic
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from rebel_dot.core.observability import AUTH_ACTIVE_SESSIONS
from rebel_dot.domain import AuthSession
from rebel_dot.ports import UnitOfWork


class InvalidCredentialsError(Exception):
    pass


class LoginRateLimitedError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class CreatedSession:
    token: str
    expires_at: datetime


@dataclass(slots=True)
class _TokenBucket:
    tokens: float
    updated_at: float


class LoginRateLimiter:
    def __init__(
        self,
        limit: int,
        window_seconds: int,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._capacity = float(limit)
        self._refill_rate = limit / window_seconds
        self._clock = clock
        self._buckets: dict[str, _TokenBucket] = {}
        self._lock = Lock()

    def consume(self, client_id: str) -> bool:
        now = self._clock()
        with self._lock:
            bucket = self._buckets.get(client_id)
            if bucket is None:
                self._buckets[client_id] = _TokenBucket(
                    tokens=self._capacity - 1,
                    updated_at=now,
                )
                return True

            elapsed = max(0.0, now - bucket.updated_at)
            available = min(
                self._capacity,
                bucket.tokens + elapsed * self._refill_rate,
            )
            bucket.updated_at = now
            if available < 1:
                bucket.tokens = available
                return False

            bucket.tokens = available - 1
            return True


def digest_session_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def utc_now() -> datetime:
    return datetime.now(UTC)


class SessionService:
    def __init__(
        self,
        *,
        password_hash: str,
        session_lifetime_seconds: int,
        unit_of_work_factory: Callable[[], UnitOfWork],
        rate_limiter: LoginRateLimiter,
        password_hasher: PasswordHasher | None = None,
        clock: Callable[[], datetime] = utc_now,
        token_factory: Callable[[], str] = generate_session_token,
    ) -> None:
        self._password_hash = password_hash
        self._session_lifetime = timedelta(seconds=session_lifetime_seconds)
        self._unit_of_work_factory = unit_of_work_factory
        self._rate_limiter = rate_limiter
        self._password_hasher = password_hasher or PasswordHasher()
        self._clock = clock
        self._token_factory = token_factory

    async def create_session(self, password: str, client_id: str) -> CreatedSession:
        if not self._rate_limiter.consume(client_id):
            raise LoginRateLimitedError

        password_matches = await asyncio.to_thread(
            self._verify_password,
            password,
        )
        if not password_matches:
            raise InvalidCredentialsError

        created_at = self._clock()
        token = self._token_factory()
        session = AuthSession(
            id=uuid4(),
            token_digest=digest_session_token(token),
            expires_at=created_at + self._session_lifetime,
            created_at=created_at,
            revoked_at=None,
            last_seen_at=None,
        )
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.sessions.prune_expired(created_at)
            await unit_of_work.sessions.add(session)
            AUTH_ACTIVE_SESSIONS.set(await unit_of_work.sessions.count_active(created_at))

        return CreatedSession(token=token, expires_at=session.expires_at)

    async def resolve_session(self, token: str) -> AuthSession | None:
        now = self._clock()
        async with self._unit_of_work_factory() as unit_of_work:
            session = await unit_of_work.sessions.get_by_digest(digest_session_token(token), now)
            AUTH_ACTIVE_SESSIONS.set(await unit_of_work.sessions.count_active(now))
            return session

    async def revoke_session(self, token: str) -> bool:
        now = self._clock()
        async with self._unit_of_work_factory() as unit_of_work:
            revoked = await unit_of_work.sessions.revoke(digest_session_token(token), now)
            AUTH_ACTIVE_SESSIONS.set(await unit_of_work.sessions.count_active(now))
            return revoked

    def _verify_password(self, password: str) -> bool:
        try:
            return self._password_hasher.verify(self._password_hash, password)
        except VerifyMismatchError:
            return False
