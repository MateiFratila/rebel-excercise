from uuid import uuid4

from rebel_dot.adapters.task_dispatcher import PollingTaskDispatcher


async def test_polling_dispatcher_leaves_committed_job_for_external_runner() -> None:
    await PollingTaskDispatcher().dispatch_embedding_job(uuid4())
