import asyncio
import re
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional

from app.core.brain import AkashiBrain, BrainResponse
from app.core.intent import analyze_intent
from app.events.hub import EventHub
from app.live.actions.base import LiveActionRuntime
from app.live.registry import LiveActionRegistry
from app.live.store import JSONInteractionStore


class InteractionCancelled(RuntimeError):
    """The user explicitly stopped an in-flight LIVE interaction."""


class InteractionManager:
    """Track one active interaction per session and support explicit cancellation."""

    def __init__(self, store: Optional[JSONInteractionStore] = None) -> None:
        self._tasks: Dict[str, asyncio.Task[BrainResponse]] = {}
        self._sessions: Dict[str, str] = {}
        self.store = store or JSONInteractionStore()
        self._lock = asyncio.Lock()

    @staticmethod
    def normalize_id(value: Optional[str]) -> str:
        if value is None:
            return str(uuid.uuid4())
        candidate = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", candidate):
            raise ValueError("Invalid interaction_id.")
        return candidate

    async def run(
        self,
        interaction_id: str,
        session_id: str,
        operation: Callable[[], Awaitable[BrainResponse]],
    ) -> BrainResponse:
        operation_task = asyncio.create_task(operation())
        old_task: Optional[asyncio.Task[BrainResponse]] = None
        async with self._lock:
            old_id = self._sessions.get(session_id)
            if old_id and old_id != interaction_id:
                old_task = self._tasks.get(old_id)
            self._tasks[interaction_id] = operation_task
            self._sessions[session_id] = interaction_id
            self.store.start(interaction_id, session_id)
        if old_task is not None and old_task is not operation_task and not old_task.done():
            old_task.cancel()
        try:
            result = await operation_task
        except asyncio.CancelledError:
            await self._set_status(
                interaction_id, "cancelled", "Interaction cancelled."
            )
            raise InteractionCancelled("Interaction cancelled.")
        except BaseException as exc:
            await self._set_status(
                interaction_id,
                "failed",
                f"Execution failed ({type(exc).__name__}).",
            )
            raise
        else:
            await self._set_status(
                interaction_id,
                "completed",
                f"{result.intent} response completed via {result.provider}.",
            )
            return result
        finally:
            async with self._lock:
                if self._tasks.get(interaction_id) is operation_task:
                    self._tasks.pop(interaction_id, None)
                if self._sessions.get(session_id) == interaction_id:
                    self._sessions.pop(session_id, None)

    async def cancel(self, interaction_id: str) -> bool:
        async with self._lock:
            task = self._tasks.get(interaction_id)
        if task is None or task.done() or task is asyncio.current_task():
            return False
        task.cancel()
        return True

    async def set_action(self, interaction_id: str, action: str) -> None:
        async with self._lock:
            self.store.update(interaction_id, action=action)

    async def _set_status(
        self, interaction_id: str, status: str, summary: str
    ) -> None:
        async with self._lock:
            self.store.update(interaction_id, status=status, summary=summary)

    async def get(self, interaction_id: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            return self.store.get(interaction_id)

    async def list(self, limit: int = 50) -> list[Dict[str, Any]]:
        async with self._lock:
            return self.store.list(limit)

    async def recover_after_restart(self) -> None:
        async with self._lock:
            self.store.recover_interrupted()


class AkashiLiveCore:
    def __init__(
        self,
        runtime: LiveActionRuntime,
        events: EventHub,
        interaction_store: Optional[JSONInteractionStore] = None,
    ) -> None:
        self.runtime = runtime
        self.events = events
        self.registry = LiveActionRegistry(runtime)
        self.interactions = InteractionManager(interaction_store)

    async def respond(
        self,
        message: str,
        session_id: str,
        mode: str,
        voice: bool,
        interaction_id: Optional[str],
        fallback: Callable[[], Awaitable[BrainResponse]],
    ) -> BrainResponse:
        normalized_id = self.interactions.normalize_id(interaction_id)

        async def operation() -> BrainResponse:
            selected = self.registry.select(message)
            if selected is None:
                return await fallback()
            action, match = selected
            await self.interactions.set_action(
                normalized_id, action.definition.name
            )
            event = {
                "interaction_id": normalized_id,
                "session_id": session_id,
                "action": action.definition.name,
                "risk": action.definition.risk,
            }
            await self.events.publish("live.action.started", event)
            try:
                result = await action.execute(
                    message, session_id, mode, voice, match
                )
            except asyncio.CancelledError:
                await self.events.publish("live.action.cancelled", event)
                raise
            except Exception as exc:
                text = action.failure_text(message, exc)
                intent = analyze_intent(message)
                self.runtime.brain.record_runtime_exchange(
                    session_id,
                    message,
                    text,
                    intent,
                    mode,  # type: ignore[arg-type]
                )
                await self.events.publish(
                    "live.action.failed", {**event, "error": text[:500]}
                )
                return BrainResponse(
                    text=text,
                    session_id=session_id,
                    provider="windows-agent",
                    intent=intent,
                )
            await self.events.publish("live.action.completed", event)
            return result

        return await self.interactions.run(
            normalized_id, session_id, operation
        )
