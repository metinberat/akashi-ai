import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

from app.events.hub import EventHub
from app.tasks.engine import TaskEngine
from app.tasks.store import JSONTaskStore
from app.tools.base import Tool, ToolDefinition
from app.tools.registry import ToolRegistry


class EchoTool(Tool):
    definition = ToolDefinition(
        name="test.echo",
        description="Echo a value.",
        input_schema={"type": "object"},
        result_schema={"type": "object"},
        risk="safe",
    )

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        await asyncio.sleep(0)
        return {"echo": arguments.get("value")}


class ConfirmTool(EchoTool):
    definition = ToolDefinition(
        name="test.confirm",
        description="Confirmation test.",
        input_schema={"type": "object"},
        result_schema={"type": "object"},
        risk="confirm",
    )


class ToolAndTaskTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(self._cleanup)
        self.registry = ToolRegistry()
        self.registry.register(EchoTool())
        self.registry.register(ConfirmTool())
        self.engine = TaskEngine(
            JSONTaskStore(Path(self.temporary.name) / "tasks.json"),
            self.registry,
            EventHub(),
        )

    async def _cleanup(self) -> None:
        for job in self.engine._jobs.values():
            if not job.done():
                job.cancel()
        await asyncio.gather(*self.engine._jobs.values(), return_exceptions=True)
        self.temporary.cleanup()

    async def test_registry_enforces_confirmation(self) -> None:
        result = await self.registry.invoke("test.echo", {"value": 4})
        self.assertEqual(result["data"]["echo"], 4)
        with self.assertRaises(PermissionError):
            await self.registry.invoke("test.confirm", {})

    async def test_task_runs_real_steps_and_persists_result(self) -> None:
        task = await self.engine.create(
            "Echo",
            [{"tool": "test.echo", "arguments": {"value": "AKASHI"}}],
        )
        await self.engine._jobs[task["id"]]
        completed = self.engine.store.get(task["id"])
        self.assertIsNotNone(completed)
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["progress"], 100)

    async def test_confirm_task_waits_then_runs_after_approval(self) -> None:
        task = await self.engine.create(
            "Confirm",
            [{"tool": "test.confirm", "arguments": {"value": 9}}],
        )
        await self.engine._jobs[task["id"]]
        self.assertEqual(self.engine.store.get(task["id"])["status"], "waiting_for_approval")
        await self.engine.approve(task["id"])
        await self.engine._jobs[task["id"]]
        self.assertEqual(self.engine.store.get(task["id"])["status"], "completed")


if __name__ == "__main__":
    unittest.main()
