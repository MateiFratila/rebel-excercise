import asyncio
from contextlib import suppress
from uuid import UUID

from rebel_dot.application.embeddings import DatabaseEmbeddingRunner


class DatabaseTaskDispatcher:
    def __init__(
        self,
        runner: DatabaseEmbeddingRunner,
        poll_interval_seconds: float,
    ) -> None:
        self._runner = runner
        self._poll_interval_seconds = poll_interval_seconds
        self._wake_event = asyncio.Event()
        self._worker: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._worker is not None:
            raise RuntimeError("task dispatcher is already running")
        self._worker = asyncio.create_task(self._work_loop())
        self._wake_event.set()

    async def close(self) -> None:
        if self._worker is None:
            return
        self._worker.cancel()
        with suppress(asyncio.CancelledError):
            await self._worker
        self._worker = None

    async def dispatch_embedding_job(self, _job_id: UUID) -> None:
        self._wake_event.set()

    async def _work_loop(self) -> None:
        while True:
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    self._wake_event.wait(),
                    timeout=self._poll_interval_seconds,
                )
            self._wake_event.clear()
            try:
                await self._runner.run_until_idle()
            except Exception:
                continue
