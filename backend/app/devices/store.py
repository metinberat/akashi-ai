import hashlib
import hmac
import json
import secrets
import string
import uuid
import time
from collections import deque
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple, cast


SAFE_ACTIONS = {
    "get_system_status",
    "list_processes",
    "application_status",
    "list_directory",
    "find_file",
    "file_metadata",
    "take_screenshot",
    "capture_camera_frame",
}
CONFIRM_ACTIONS = {
    "launch_application",
    "open_project",
    "reveal_file",
    "run_project_script",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_text(value: Optional[datetime] = None) -> str:
    return (value or utc_now()).isoformat()


def _token_digest(token: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", token.encode("utf-8"), salt, 180_000).hex()


class DeviceStore:
    """JSON registry containing only salted device-token hashes."""

    def __init__(self, file_path: Path, code_ttl: int, online_ttl: int) -> None:
        self.file_path = file_path
        self.code_ttl = max(60, code_ttl)
        self.online_ttl = max(15, online_ttl)
        self._lock = Lock()
        self._pair_attempts = deque(maxlen=31)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self.file_path.write_text(
                json.dumps(
                    {"version": 1, "devices": [], "pairing_codes": [], "actions": []},
                    indent=2,
                ),
                encoding="utf-8",
            )

    def _read(self) -> Dict[str, Any]:
        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Invalid device store")
            data.setdefault("devices", [])
            data.setdefault("pairing_codes", [])
            data.setdefault("actions", [])
            return cast(Dict[str, Any], data)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Device store at '{self.file_path}' is unreadable; it was not overwritten."
            ) from exc

    def _write(self, data: Dict[str, Any]) -> None:
        temporary = self.file_path.with_suffix(f"{self.file_path.suffix}.tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.file_path)

    @staticmethod
    def _public_device(device: Dict[str, Any], online_ttl: int) -> Dict[str, Any]:
        last_seen = device.get("last_seen")
        online = False
        if last_seen and not device.get("revoked"):
            try:
                online = utc_now() - datetime.fromisoformat(last_seen) < timedelta(seconds=online_ttl)
            except ValueError:
                online = False
        return {
            key: deepcopy(value)
            for key, value in device.items()
            if key not in {"token_hash", "token_salt"}
        } | {"online": online}

    def create_pairing_code(self) -> Dict[str, Any]:
        alphabet = string.ascii_uppercase + string.digits
        code = "".join(secrets.choice(alphabet) for _ in range(10))
        expires = utc_now() + timedelta(seconds=self.code_ttl)
        record = {
            "id": str(uuid.uuid4()),
            "code_hash": hashlib.sha256(code.encode("utf-8")).hexdigest(),
            "created_at": utc_text(),
            "expires_at": utc_text(expires),
        }
        with self._lock:
            data = self._read()
            data["pairing_codes"] = [
                item
                for item in data["pairing_codes"]
                if datetime.fromisoformat(item["expires_at"]) > utc_now()
            ]
            data["pairing_codes"].append(record)
            self._write(data)
        return {"code": code, "expires_at": record["expires_at"]}

    def pair(
        self,
        code: str,
        name: str,
        device_type: str,
        capabilities: List[str],
    ) -> Tuple[Dict[str, Any], str]:
        code_hash = hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()
        with self._lock:
            data = self._read()
            match = next(
                (
                    item for item in data["pairing_codes"]
                    if hmac.compare_digest(item.get("code_hash", ""), code_hash)
                    and datetime.fromisoformat(item["expires_at"]) > utc_now()
                ),
                None,
            )
            now = time.monotonic()
            while self._pair_attempts and now - self._pair_attempts[0] > 60:
                self._pair_attempts.popleft()
            if len(self._pair_attempts) >= 30:
                raise PermissionError("Pairing rate limit reached. Wait one minute.")
            self._pair_attempts.append(now)
            if match is None:
                raise PermissionError("Pairing code is invalid or expired.")
            data["pairing_codes"] = [item for item in data["pairing_codes"] if item is not match]
            token = secrets.token_urlsafe(48)
            salt = secrets.token_bytes(16)
            now = utc_text()
            device = {
                "id": str(uuid.uuid4()),
                "name": name.strip()[:100] or "AKASHI Desktop",
                "device_type": device_type.strip().lower()[:40] or "desktop",
                "capabilities": sorted({item.strip() for item in capabilities if item.strip()}),
                "created_at": now,
                "last_seen": now,
                "revoked": False,
                "token_salt": salt.hex(),
                "token_hash": _token_digest(token, salt),
            }
            data["devices"].append(device)
            self._write(data)
        return self._public_device(device, self.online_ttl), token

    def authenticate(self, device_id: str, token: str, touch: bool = True) -> Optional[Dict[str, Any]]:
        if len(token) > 512 or len(device_id) > 128:
            return None
        with self._lock:
            data = self._read()
            device = next(
                (item for item in data["devices"] if item.get("id") == device_id),
                None,
            )
            if device is None or device.get("revoked"):
                return None
            try:
                actual = _token_digest(token, bytes.fromhex(device["token_salt"]))
            except (KeyError, ValueError):
                return None
            if not hmac.compare_digest(actual, device.get("token_hash", "")):
                return None
            if touch:
                device["last_seen"] = utc_text()
                self._write(data)
            return self._public_device(device, self.online_ttl)

    def list_devices(self) -> List[Dict[str, Any]]:
        with self._lock:
            devices = list(self._read()["devices"])
        return [self._public_device(item, self.online_ttl) for item in devices]

    def revoke(self, device_id: str) -> bool:
        with self._lock:
            data = self._read()
            device = next((item for item in data["devices"] if item.get("id") == device_id), None)
            if device is None:
                return False
            device["revoked"] = True
            device["revoked_at"] = utc_text()
            data["actions"] = [item for item in data["actions"] if item.get("device_id") != device_id]
            self._write(data)
            return True

    @staticmethod
    def action_risk(action: str) -> str:
        if action in SAFE_ACTIONS:
            return "safe"
        if action in CONFIRM_ACTIONS:
            return "confirm"
        raise ValueError("Unsupported or restricted device action.")

    def queue_action(
        self,
        device_id: str,
        action: str,
        arguments: Dict[str, Any],
        approved: bool,
    ) -> Dict[str, Any]:
        risk = self.action_risk(action)
        if risk == "confirm" and not approved:
            raise PermissionError("This device action requires explicit approval.")
        if len(json.dumps(arguments)) > 64_000:
            raise ValueError("Action arguments are too large.")
        with self._lock:
            data = self._read()
            device = next(
                (item for item in data["devices"] if item.get("id") == device_id and not item.get("revoked")),
                None,
            )
            if device is None:
                raise KeyError("Device was not found.")
            capabilities = set(device.get("capabilities", []))
            if action not in capabilities:
                raise ValueError("The paired device did not advertise this capability.")
            if sum(item.get("status") in {"queued", "dispatched"} for item in data["actions"]) >= 100:
                raise ValueError("Device action queue is full. Resolve pending actions first.")
            now = utc_text()
            queued = {
                "id": str(uuid.uuid4()),
                "device_id": device_id,
                "action": action,
                "arguments": deepcopy(arguments),
                "risk": risk,
                "approved": approved,
                "status": "queued",
                "created_at": now,
                "updated_at": now,
                "expires_at": utc_text(utc_now() + timedelta(minutes=10)),
                "result": None,
                "error": None,
            }
            data["actions"].append(queued)
            self._write(data)
            return deepcopy(queued)

    def poll_actions(self, device_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        with self._lock:
            data = self._read()
            now = utc_now()
            selected = []
            for action in data["actions"]:
                if action.get("device_id") != device_id:
                    continue
                if action.get("status") == "dispatched":
                    try:
                        dispatched = datetime.fromisoformat(action["updated_at"])
                        if now - dispatched > timedelta(minutes=10):
                            action["status"] = "unknown"
                            action["error"] = "Acknowledgement missing. Execution outcome unknown; not retried."
                    except (KeyError, ValueError):
                        action["status"] = "unknown"
                if action.get("status") == "queued" and now - datetime.fromisoformat(action["created_at"]) > timedelta(minutes=10):
                    action["status"] = "expired"
                    action["error"] = "Action expired before dispatch. Submit a new request if still needed."
                if action.get("status") == "queued" and len(selected) < max(1, min(limit, 10)):
                    action["status"] = "dispatched"
                    action["updated_at"] = utc_text(now)
                    selected.append(deepcopy(action))
            self._write(data)
            return selected

    def complete_action(
        self,
        device_id: str,
        action_id: str,
        ok: bool,
        result: Optional[Dict[str, Any]],
        error: Optional[str],
    ) -> Dict[str, Any]:
        payload_size = len(json.dumps(result or {}))
        if payload_size > 2_000_000:
            raise ValueError("Action result is too large.")
        with self._lock:
            data = self._read()
            action = next(
                (
                    item for item in data["actions"]
                    if item.get("id") == action_id and item.get("device_id") == device_id
                ),
                None,
            )
            if action is None:
                raise KeyError("Device action was not found.")
            if action["status"] in {"completed", "failed"}:
                return deepcopy(action)  # Idempotent acknowledgement; immutable result.
            if action["status"] not in {"dispatched", "unknown"}:
                raise ValueError("Only a dispatched action can be completed.")
            action["status"] = "completed" if ok else "failed"
            action["result"] = deepcopy(result) if ok else None
            action["error"] = None if ok else (error or "Device action failed.")[:1_000]
            action["updated_at"] = utc_text()
            self._write(data)
            return deepcopy(action)

    def get_action(self, action_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            action = next(
                (item for item in self._read()["actions"] if item.get("id") == action_id),
                None,
            )
        return deepcopy(action) if action else None
