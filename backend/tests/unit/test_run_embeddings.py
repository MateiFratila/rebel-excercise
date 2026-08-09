import signal
from collections.abc import Callable
from pathlib import Path as SyncPath
from types import SimpleNamespace

from anyio import Path
from pydantic import SecretStr

from rebel_dot.ops import run_embeddings


class FakeConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, statement: object) -> None:
        self.statements.append(str(statement))


class FakeConnectionContext:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> FakeConnection:
        return self.connection

    async def __aexit__(
        self,
        _exception_type: object,
        _exception: object,
        _traceback: object,
    ) -> None:
        return None


class FakeEngine:
    def __init__(self) -> None:
        self.connection = FakeConnection()
        self.disposed = False

    def connect(self) -> FakeConnectionContext:
        return FakeConnectionContext(self.connection)

    async def dispose(self) -> None:
        self.disposed = True


class FakeDispatcher:
    def __init__(self) -> None:
        self.started = False
        self.closed = False

    async def start(self) -> None:
        self.started = True

    async def close(self) -> None:
        self.closed = True


class FakeLoop:
    def __init__(self) -> None:
        self.signals: list[int] = []

    def add_signal_handler(self, signal_number: int, callback: Callable[[], None]) -> None:
        self.signals.append(signal_number)
        if signal_number == signal.SIGTERM:
            callback()


async def test_runner_probes_database_and_cleans_up_on_signal(
    monkeypatch: object,
    tmp_path: SyncPath,
) -> None:
    engine = FakeEngine()
    dispatcher = FakeDispatcher()
    loop = FakeLoop()
    ready_path = Path(tmp_path / "runner-ready")
    settings = SimpleNamespace(
        database_url="postgresql+asyncpg://example.test/faq",
        embedding_model="text-embedding-3-small",
        embedding_dimensions=1536,
        openai_api_key=SecretStr("test-only"),
        openai_timeout_seconds=10,
        openai_max_retries=0,
        embedding_batch_size=64,
        job_stale_after_seconds=300,
        job_poll_interval_seconds=5,
    )
    created: dict[str, object] = {}

    monkeypatch.setattr(run_embeddings, "Settings", lambda: settings)  # type: ignore[attr-defined]
    monkeypatch.setattr(run_embeddings, "READY_PATH", ready_path)  # type: ignore[attr-defined]
    monkeypatch.setattr(run_embeddings, "create_database_engine", lambda _url: engine)  # type: ignore[attr-defined]
    monkeypatch.setattr(run_embeddings, "create_session_factory", lambda _engine: object())  # type: ignore[attr-defined]
    monkeypatch.setattr(run_embeddings, "SQLAlchemyUnitOfWork", lambda _factory: object())  # type: ignore[attr-defined]
    monkeypatch.setattr(run_embeddings, "OpenAIEmbeddingProvider", lambda **kwargs: kwargs)  # type: ignore[attr-defined]

    def create_runner(**kwargs: object) -> object:
        created["unit_of_work"] = kwargs["unit_of_work_factory"]()  # type: ignore[operator]
        created["runner"] = kwargs
        return object()

    def create_dispatcher(runner: object, poll_interval_seconds: float) -> FakeDispatcher:
        created["dispatcher_runner"] = runner
        created["poll_interval_seconds"] = poll_interval_seconds
        return dispatcher

    monkeypatch.setattr(run_embeddings, "DatabaseEmbeddingRunner", create_runner)  # type: ignore[attr-defined]
    monkeypatch.setattr(run_embeddings, "DatabaseTaskDispatcher", create_dispatcher)  # type: ignore[attr-defined]
    monkeypatch.setattr(run_embeddings.asyncio, "get_running_loop", lambda: loop)  # type: ignore[attr-defined]

    await run_embeddings.run()

    assert engine.connection.statements == ["SELECT 1"]
    assert dispatcher.started
    assert dispatcher.closed
    assert engine.disposed
    assert loop.signals == [signal.SIGINT, signal.SIGTERM]
    assert created["poll_interval_seconds"] == 5
    assert not await ready_path.exists()
