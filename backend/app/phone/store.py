import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Literal, Optional


CallState = Literal[
    "ringing",
    "answered",
    "connected",
    "caller_speaking",
    "assistant_speaking",
    "ended",
    "failed",
]
CallDirection = Literal["inbound", "outbound"]
TERMINAL_STATES = {"ended", "failed"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_text(value: Optional[datetime] = None) -> str:
    return (value or utc_now()).isoformat()


class JSONPhoneCallStore:
    """Bounded local call history with atomic writes and no credential fields."""

    def __init__(self, file_path: Path, limit: int = 250) -> None:
        self.file_path = file_path
        self.limit = max(25, min(limit, 2_000))
        self._lock = Lock()
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self._write({"version": 1, "calls": []})

    def _read(self) -> Dict[str, Any]:
        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("calls"), list):
                raise ValueError("Invalid phone call document")
            return data
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("Phone call history is unreadable; it was not overwritten.") from exc

    def _write(self, data: Dict[str, Any]) -> None:
        data["calls"] = data.get("calls", [])[-self.limit :]
        temporary = self.file_path.with_suffix(f"{self.file_path.suffix}.tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.file_path)

    @staticmethod
    def _duration(item: Dict[str, Any]) -> int:
        start_value = item.get("connected_at") or item.get("answered_at") or item.get("started_at")
        if not start_value:
            return 0
        try:
            start = datetime.fromisoformat(str(start_value))
            end = datetime.fromisoformat(str(item["ended_at"])) if item.get("ended_at") else utc_now()
            return max(0, int((end - start).total_seconds()))
        except ValueError:
            return 0

    def _public(self, item: Dict[str, Any]) -> Dict[str, Any]:
        value = deepcopy(item)
        value["duration_seconds"] = self._duration(value)
        return value

    def update(
        self,
        call_id: str,
        state: CallState,
        *,
        direction: CallDirection = "inbound",
        room_name: str = "",
        caller_number: str = "unknown",
        callee_number: Optional[str] = None,
        transcript_role: Optional[Literal["caller", "assistant"]] = None,
        transcript_text: Optional[str] = None,
        transcript_final: bool = True,
        result: Optional[str] = None,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = utc_text()
        with self._lock:
            data = self._read()
            calls = data["calls"]
            item = next((value for value in calls if value.get("id") == call_id), None)
            if item is None:
                item = {
                    "id": call_id[:128],
                    "direction": direction,
                    "room_name": room_name[:128],
                    "caller_number": caller_number[:64],
                    "callee_number": callee_number[:64] if callee_number else None,
                    "state": state,
                    "started_at": now,
                    "answered_at": None,
                    "connected_at": None,
                    "ended_at": None,
                    "transcript": [],
                    "result": None,
                    "error": None,
                    "updated_at": now,
                }
                calls.append(item)
            elif item.get("state") in TERMINAL_STATES and state not in TERMINAL_STATES:
                return self._public(item)

            item["state"] = state
            item["updated_at"] = now
            if room_name:
                item["room_name"] = room_name[:128]
            if caller_number and caller_number != "unknown":
                item["caller_number"] = caller_number[:64]
            if callee_number:
                item["callee_number"] = callee_number[:64]
            if state == "answered" and not item.get("answered_at"):
                item["answered_at"] = now
            if state == "connected" and not item.get("connected_at"):
                item["connected_at"] = now
            if state in TERMINAL_STATES:
                item["ended_at"] = item.get("ended_at") or now
            if result is not None:
                item["result"] = result[:500]
            if error is not None:
                item["error"] = error[:500]
            if transcript_role and transcript_text and transcript_text.strip():
                transcript = {
                    "role": transcript_role,
                    "content": transcript_text.strip()[:4_000],
                    "final": bool(transcript_final),
                    "timestamp": now,
                }
                previous = item["transcript"][-1] if item["transcript"] else None
                if previous and not previous.get("final") and previous.get("role") == transcript_role:
                    item["transcript"][-1] = transcript
                elif not previous or previous.get("content") != transcript["content"] or previous.get("role") != transcript_role:
                    item["transcript"].append(transcript)
                item["transcript"] = item["transcript"][-500:]
            self._write(data)
            return self._public(item)

    def get(self, call_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            item = next((value for value in self._read()["calls"] if value.get("id") == call_id), None)
            return self._public(item) if item else None

    def list(self, limit: int = 30, active_only: bool = False) -> List[Dict[str, Any]]:
        bounded = max(1, min(limit, 100))
        with self._lock:
            calls = self._read()["calls"]
            if active_only:
                calls = [item for item in calls if item.get("state") not in TERMINAL_STATES]
            return [self._public(item) for item in reversed(calls[-bounded:])]

