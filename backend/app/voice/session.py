from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Literal, Optional
import uuid


VoiceState = Literal[
    "idle", "listening", "transcribing", "thinking", "acting",
    "speaking", "interrupted", "error",
]

TRANSITIONS = {
    "idle": {"listening", "error"},
    "listening": {"transcribing", "interrupted", "idle", "error"},
    "transcribing": {"thinking", "listening", "interrupted", "error"},
    "thinking": {"acting", "speaking", "listening", "interrupted", "error"},
    "acting": {"speaking", "listening", "interrupted", "error"},
    "speaking": {"listening", "interrupted", "idle", "error"},
    "interrupted": {"listening", "idle", "error"},
    "error": {"listening", "idle"},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class VoiceSessionManager:
    """Voice lifecycle with privacy-safe restart metadata.

    Raw audio and utterance text remain process-local. Persisted records contain
    only lifecycle identifiers, state, language, generation, and timestamps.
    """

    def __init__(self, state_file: Optional[Path] = None) -> None:
        self._sessions: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._lock = Lock()
        self.state_file = state_file
        if self.state_file is not None:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            if self.state_file.exists():
                self._load()
            else:
                self._persist_locked()

    def recover_after_restart(self) -> int:
        return self.interrupt_all(
            "Backend restarted; start a fresh voice session."
        )

    def _safe_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": str(item["id"])[:128],
            "session_id": str(item["session_id"])[:128],
            "interaction_id": (
                str(item["interaction_id"])[:128]
                if item.get("interaction_id")
                else None
            ),
            "state": str(item["state"])[:32],
            "language": str(item.get("language", "auto"))[:16],
            "generation": int(item.get("generation", 1)),
            "error": str(item["error"])[:500] if item.get("error") else None,
            "started_at": str(item["started_at"]),
            "updated_at": str(item["updated_at"]),
        }

    def _load(self) -> None:
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))  # type: ignore[union-attr]
            sessions = data.get("sessions") if isinstance(data, dict) else None
            if not isinstance(sessions, list):
                raise ValueError("Invalid voice state document")
            for stored in sessions[-200:]:
                if not isinstance(stored, dict) or not stored.get("id"):
                    continue
                item = self._safe_item(stored)
                item["last_user_utterance"] = None
                item["last_assistant_utterance"] = None
                self._sessions[item["id"]] = item
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "Voice session state is unreadable; it was not overwritten."
            ) from exc

    def _persist_locked(self) -> None:
        if self.state_file is None:
            return
        document = {
            "version": 1,
            "sessions": [self._safe_item(item) for item in self._sessions.values()],
        }
        temporary = self.state_file.with_suffix(f"{self.state_file.suffix}.tmp")
        temporary.write_text(
            json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.state_file)

    def start(self, session_id: str, language: str = "auto") -> Dict[str, Any]:
        now = _now()
        item = {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "interaction_id": None,
            "state": "listening",
            "language": language if language in {"auto", "tr", "en"} else "auto",
            "generation": 1,
            "last_user_utterance": None,
            "last_assistant_utterance": None,
            "error": None,
            "started_at": now,
            "updated_at": now,
        }
        with self._lock:
            self._sessions[item["id"]] = item
            while len(self._sessions) > 200:
                self._sessions.popitem(last=False)
            self._persist_locked()
        return deepcopy(item)

    def get(self, voice_session_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            value = self._sessions.get(voice_session_id)
        return deepcopy(value) if value else None

    def transition(
        self,
        voice_session_id: str,
        state: VoiceState,
        interaction_id: Optional[str] = None,
        last_user_utterance: Optional[str] = None,
        last_assistant_utterance: Optional[str] = None,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            item = self._sessions.get(voice_session_id)
            if item is None:
                raise KeyError("Voice session was not found.")
            current = item["state"]
            if state != current and state not in TRANSITIONS[current]:
                raise ValueError(f"Invalid voice transition: {current} -> {state}.")
            item["state"] = state
            if interaction_id is not None:
                item["interaction_id"] = interaction_id[:128]
            if last_user_utterance is not None:
                item["last_user_utterance"] = last_user_utterance[:2_000]
            if last_assistant_utterance is not None:
                item["last_assistant_utterance"] = last_assistant_utterance[:2_000]
            item["error"] = error[:500] if error else None
            item["updated_at"] = _now()
            self._persist_locked()
            return deepcopy(item)

    def interrupt(self, voice_session_id: str) -> Dict[str, Any]:
        with self._lock:
            item = self._sessions.get(voice_session_id)
            if item is None:
                raise KeyError("Voice session was not found.")
            item["state"] = "interrupted"
            item["generation"] += 1
            item["interaction_id"] = None
            item["updated_at"] = _now()
            self._persist_locked()
            return deepcopy(item)

    def interrupt_all(self, reason: str) -> int:
        count = 0
        with self._lock:
            for item in self._sessions.values():
                if item.get("state") == "interrupted" and item.get("error") == reason[:500]:
                    continue
                item["state"] = "interrupted"
                item["generation"] = int(item.get("generation", 1)) + 1
                item["interaction_id"] = None
                item["last_user_utterance"] = None
                item["last_assistant_utterance"] = None
                item["error"] = reason[:500]
                item["updated_at"] = _now()
                count += 1
            self._persist_locked()
        return count

    def stop(self, voice_session_id: str) -> bool:
        with self._lock:
            removed = self._sessions.pop(voice_session_id, None) is not None
            self._persist_locked()
            return removed
