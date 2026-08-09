from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rebel_dot.adapters.db.repositories import (
    SQLAlchemyCollectionRepository,
    SQLAlchemyEmbeddingJobRepository,
    SQLAlchemyFAQRepository,
    SQLAlchemySessionRepository,
)


class SQLAlchemyUnitOfWork:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self.collections: SQLAlchemyCollectionRepository
        self.faqs: SQLAlchemyFAQRepository
        self.jobs: SQLAlchemyEmbeddingJobRepository
        self.sessions: SQLAlchemySessionRepository

    async def __aenter__(self) -> "SQLAlchemyUnitOfWork":
        if self._session is not None:
            raise RuntimeError("unit of work is already active")

        self._session = self._session_factory()
        self.collections = SQLAlchemyCollectionRepository(self._session)
        self.faqs = SQLAlchemyFAQRepository(self._session)
        self.jobs = SQLAlchemyEmbeddingJobRepository(self._session)
        self.sessions = SQLAlchemySessionRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._session is None:
            return

        try:
            if exc_type is None:
                await self._session.commit()
            else:
                await self._session.rollback()
        finally:
            await self._session.close()
            self._session = None
