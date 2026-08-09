import asyncio
import signal

from anyio import Path
from sqlalchemy import text

from rebel_dot.adapters.db.database import create_database_engine, create_session_factory
from rebel_dot.adapters.db.unit_of_work import SQLAlchemyUnitOfWork
from rebel_dot.adapters.openai_embeddings import OpenAIEmbeddingProvider
from rebel_dot.adapters.task_dispatcher import DatabaseTaskDispatcher
from rebel_dot.application.embeddings import DatabaseEmbeddingRunner
from rebel_dot.core import Settings
from rebel_dot.ports import UnitOfWork

READY_PATH = Path("/tmp/rebel-dot-runner-ready")


async def run() -> None:
    settings = Settings()  # type: ignore[call-arg]
    engine = create_database_engine(str(settings.database_url))
    session_factory = create_session_factory(engine)

    def create_unit_of_work() -> UnitOfWork:
        return SQLAlchemyUnitOfWork(session_factory)

    provider = OpenAIEmbeddingProvider(
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        api_key=settings.openai_api_key,
        timeout_seconds=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
        batch_size=settings.embedding_batch_size,
    )
    dispatcher = DatabaseTaskDispatcher(
        DatabaseEmbeddingRunner(
            unit_of_work_factory=create_unit_of_work,
            provider=provider,
            batch_size=settings.embedding_batch_size,
            stale_after_seconds=settings.job_stale_after_seconds,
        ),
        poll_interval_seconds=settings.job_poll_interval_seconds,
    )
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_number, stop_event.set)

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        await dispatcher.start()
        await READY_PATH.touch()
        await stop_event.wait()
    finally:
        await READY_PATH.unlink(missing_ok=True)
        await dispatcher.close()
        await engine.dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
