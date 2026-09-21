import asyncio
import uuid
from typing import Any, Dict, List, Optional

from app.events.hub import EventHub
from app.tasks.store import JSONTaskStore, utc_now
from app.tools.registry import ToolRegistry
from app.tools.validation import validate_arguments


class TaskEngine:
    """Runs explicit tool steps asynchronously with persisted state."""

    def __init__(self, store: JSONTaskStore, tools: ToolRegistry, events: EventHub) -> None:
        self.store = store
        self.tools = tools
        self.events = events
        self._jobs: Dict[str, asyncio.Task[None]] = {}

    async def create(
        self,
        title: str,
        steps: List[Dict[str, Any]],
        approved: bool = False,
    ) -> Dict[str, Any]:
        if not title.strip():
            raise ValueError("Task title cannot be empty.")
        if not steps or len(steps) > 25:
            raise ValueError("A task requires between 1 and 25 explicit steps.")
        normalized_steps = []
        for item in steps:
            tool_name = str(item.get("tool") or "")
            tool = self.tools.get(tool_name)
            if tool.definition.risk == "restricted":
                raise PermissionError(f"Restricted tool '{tool_name}' cannot be scheduled.")
            arguments = item.get("arguments", {})
            if not isinstance(arguments, dict):
                raise ValueError("Step arguments must be an object.")
            validate_arguments(arguments, tool.definition.input_schema)
            normalized_steps.append(
                {
                    "id": str(uuid.uuid4()),
                    "tool": tool_name,
                    "arguments": arguments,
                    "risk": tool.definition.risk,
                    "status": "queued",
                    "result": None,
                    "error": None,
                    "started_at": None,
                    "completed_at": None,
                }
            )
        now = utc_now()
        task = {
            "id": str(uuid.uuid4()),
            "title": title.strip(),
            "status": "queued",
            "steps": normalized_steps,
            "progress": 0,
            "approved": bool(approved),
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
            "result": None,
            "error": None,
        }
        self.store.create(task)
        await self.events.publish("task.created", self._event_payload(task))
        self._schedule(task["id"])
        return task

    def _schedule(self, task_id: str) -> None:
        active = self._jobs.get(task_id)
        if active is not None and not active.done():
            active.add_done_callback(lambda _job: self._schedule(task_id))
            return
        self._jobs[task_id] = asyncio.create_task(self._run(task_id))
        job = self._jobs[task_id]
        job.add_done_callback(lambda finished: self._jobs.pop(task_id, None) if self._jobs.get(task_id) is finished else None)

    async def _run(self, task_id: str) -> None:
        task = self.store.get(task_id)
        if task is None or task["status"] not in {"queued", "waiting_for_approval"}:
            return
        task["status"] = "planning"
        task["updated_at"] = utc_now()
        self.store.replace(task)
        await self.events.publish("task.updated", self._event_payload(task))

        if any(step["risk"] == "confirm" for step in task["steps"]) and not task["approved"]:
            task["status"] = "waiting_for_approval"
            task["updated_at"] = utc_now()
            self.store.replace(task)
            await self.events.publish("task.updated", self._event_payload(task))
            return

        task["status"] = "running"
        task["updated_at"] = utc_now()
        self.store.replace(task)
        await self.events.publish("task.updated", self._event_payload(task))
        try:
            for index, step in enumerate(task["steps"]):
                current = self.store.get(task_id)
                if current is None or current["status"] == "cancelled":
                    return
                task = current
                step = task["steps"][index]
                step["status"] = "running"
                step["started_at"] = utc_now()
                task["updated_at"] = utc_now()
                self.store.replace(task)
                await self.events.publish("task.step", self._event_payload(task, index))
                result = await self.tools.invoke(
                    step["tool"],
                    step["arguments"],
                    approved=bool(task["approved"]),
                )
                latest = self.store.get(task_id)
                if not latest or latest["status"] == "cancelled":
                    return
                step["status"] = "completed"
                step["result"] = result
                step["completed_at"] = utc_now()
                task["progress"] = round((index + 1) / len(task["steps"]) * 100)
                task["updated_at"] = utc_now()
                self.store.replace(task)
                await self.events.publish("task.step", self._event_payload(task, index))
            task["status"] = "completed"
            task["completed_at"] = utc_now()
            task["updated_at"] = task["completed_at"]
            task["result"] = [step["result"] for step in task["steps"]]
            self.store.replace(task)
            await self.events.publish("task.completed", self._event_payload(task))
        except asyncio.CancelledError:
            current = self.store.get(task_id)
            if current and current["status"] != "cancelled":
                current["status"] = "cancelled"
                current["updated_at"] = utc_now()
                self.store.replace(current)
            raise
        except Exception as exc:
            current = self.store.get(task_id) or task
            current["status"] = "failed"
            current["error"] = str(exc)[:1_000]
            current["updated_at"] = utc_now()
            for step in current["steps"]:
                if step["status"] == "running":
                    step["status"] = "failed"
                    step["error"] = str(exc)[:1_000]
                    step["completed_at"] = utc_now()
            self.store.replace(current)
            await self.events.publish("task.failed", self._event_payload(current))

    async def approve(self, task_id: str) -> Dict[str, Any]:
        task = self._required(task_id)
        if task["status"] != "waiting_for_approval":
            raise ValueError("Only a task waiting for approval can be approved.")
        task["approved"] = True
        task["status"] = "queued"
        task["updated_at"] = utc_now()
        self.store.replace(task)
        self._schedule(task_id)
        return task

    async def cancel(self, task_id: str) -> Dict[str, Any]:
        task = self._required(task_id)
        if task["status"] in {"completed", "failed", "cancelled"}:
            return task
        task["status"] = "cancelled"
        task["updated_at"] = utc_now()
        self.store.replace(task)
        job = self._jobs.get(task_id)
        if job and not job.done():
            job.cancel()
        await self.events.publish("task.cancelled", self._event_payload(task))
        return task

    def _required(self, task_id: str) -> Dict[str, Any]:
        task = self.store.get(task_id)
        if task is None:
            raise KeyError("Task was not found.")
        return task

    @staticmethod
    def _event_payload(task: Dict[str, Any], step_index: Optional[int] = None) -> Dict[str, Any]:
        payload = {
            "task_id": task["id"],
            "title": task["title"],
            "status": task["status"],
            "progress": task["progress"],
        }
        if step_index is not None:
            payload["step"] = task["steps"][step_index]
        return payload
