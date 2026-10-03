"""Async AKASHI host adapter. The numeric training domain has no host dependency."""
import asyncio


class TrainingCoordinator:
    def __init__(self, engine):
        self.engine = engine
        self.worker = None
        self.active_id = None
        self.error = None

    async def start(self, identifier):
        if self.worker and not self.worker.done():
            raise ValueError("Local training compute already has an active worker.")
        run = await asyncio.to_thread(self.engine.repository.get, identifier)
        if self.worker and not self.worker.done():
            raise ValueError("Local training compute already has an active worker.")
        if run["status"] in {"completed", "cancelled", "failed"}:
            return run
        self.active_id, self.error = identifier, None
        async def work():
            try:
                while True:
                    value = await asyncio.to_thread(self.engine.run, identifier, 1, 120)
                    if value["status"] in {"completed", "cancelled", "failed", "paused_recovery"} or value["pause_requested"] or self.engine.stopping.is_set():
                        return
                    await asyncio.sleep(.05)
            except Exception as exc:
                self.error = type(exc).__name__
                await asyncio.to_thread(self.engine.repository.dispatch_failure, identifier, self.error)
        self.worker = asyncio.create_task(work(), name="character-training-"+identifier)
        return {**run, "worker_dispatched": True}

    async def shutdown(self):
        self.engine.shutdown()
        if self.active_id:
            await asyncio.to_thread(self.engine.repository.request, self.active_id, "pause")
        if self.worker:
            # Numeric candidates are bounded. Never cancel to_thread and pretend the worker stopped.
            await self.worker
