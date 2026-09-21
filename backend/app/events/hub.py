import asyncio
from collections import deque
from uuid import uuid4
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, Set


class EventHub:
    """Small process-local fan-out hub; REST remains the source of truth."""

    def __init__(self) -> None:
        self._subscribers: Set[asyncio.Queue[Dict[str, Any]]] = set()
        self._recent = deque(maxlen=150)
        self._sequence = 0
        self.instance = str(uuid4())

    async def publish(self, event_type: str, data: Dict[str, Any]) -> None:
        self._sequence += 1
        event = {
            "id": self._sequence,
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        # Observable metadata only. Source text, tool arguments/results, tokens,
        # private content and model reasoning never enter the HUD feed.
        allowed = {"request_id", "interaction_id", "task_id", "state", "status", "action", "source_count", "tool", "step_id"}
        self._recent.append({**event, "data": {
            key: value for key, value in data.items()
            if key in allowed and isinstance(value, (str, int, bool))
            and (not isinstance(value, str) or len(value) <= 160)
        }})
        for queue in tuple(self._subscribers):
            try:
                queue.put_nowait(event)

            except asyncio.QueueFull:
                # Drop the oldest notification, not the subscriber. REST owns state.
                queue.get_nowait()
                queue.put_nowait(event)

    def recent(self, after: int = 0) -> Dict[str, Any]:
        return {"instance": self.instance, "cursor": self._sequence,
                "events": [event for event in self._recent if event["id"] > after]}

    async def subscribe(self) -> AsyncIterator[Dict[str, Any]]:
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        try:
            while True:
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=20.0)
                except asyncio.TimeoutError:
                    yield {
                        "type": "heartbeat",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "data": {},
                    }
        finally:
            self._subscribers.discard(queue)


event_hub = EventHub()
