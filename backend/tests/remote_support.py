"""Shared helpers for remote presence tests: device keys, clocks, a protocol client."""

from __future__ import annotations

import base64
import itertools
import json
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from app.core.config import Settings
from app.remote import identity

API_TOKEN = "remote-test-api-token-0000000000000000"


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


class DeviceKey:
    """A P-256 key that signs the way WebCrypto does (IEEE P1363 r||s)."""

    def __init__(self) -> None:
        self.private = ec.generate_private_key(ec.SECP256R1())

    def jwk(self) -> Dict[str, str]:
        numbers = self.private.public_key().public_numbers()
        return {"kty": "EC", "crv": "P-256", "x": b64url(numbers.x.to_bytes(32, "big")), "y": b64url(numbers.y.to_bytes(32, "big"))}

    def sign(self, message: bytes) -> str:
        r, s = decode_dss_signature(self.private.sign(message, ec.ECDSA(hashes.SHA256())))
        return b64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))

    def proof(self, device_id: str, nonce: str, scopes: Optional[Iterable[str]] = None) -> str:
        return self.sign(identity.proof_message(device_id, nonce, scopes))


class Clock:
    """Deterministic monotonic + wall clock (milliseconds) for hub tests."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def monotonic(self) -> float:
        return self.now

    def wall_ms(self) -> float:
        return 1_700_000_000_000.0 + self.now * 1000.0

    def advance(self, seconds: float) -> None:
        self.now += seconds


def settings_for(root: Path, **extra: Any) -> Settings:
    return Settings(
        ai_provider="mock", api_token=API_TOKEN, memory_file=root / "memory.json", long_term_memory_file=root / "lt.json",
        task_file=root / "tasks.json", upload_dir=root / "uploads", file_index_file=root / "files.json",
        device_file=root / "devices.json", intelligence_file=root / "intel.json", schedule_file=root / "schedules.json",
        phone_calls_file=root / "phone.json", autonomy_state_file=root / "autonomy.json",
        autonomy_knowledge_file=root / "knowledge.json", autonomy_skill_file=root / "skills.json",
        expertise_db=root / "expertise.sqlite3", live_state_file=root / "live.json",
        computer_state_file=root / "computer.json", voice_state_file=root / "voice.json",
        spatial_dir=root / "spatial", spatial_form_data_dir=root / "no-form", **extra)


class Envelopes:
    """Builds client envelopes with a monotonic seq and a client clock."""

    def __init__(self, clock_ms=lambda: 5_000_000.0) -> None:
        self.seq = itertools.count(1)
        self.ids = itertools.count(1)
        self.clock_ms = clock_ms

    def make(self, kind: str, body: Optional[Dict[str, Any]] = None, *, seq: Optional[int] = None,
             message_id: Optional[str] = None, t: Optional[float] = None) -> Dict[str, Any]:
        return {"v": 1, "id": message_id or f"msg-{next(self.ids):06d}", "seq": seq if seq is not None else next(self.seq),
                "t": self.clock_ms() if t is None else t, "kind": kind, "body": body or {}}


async def pair_and_open(hub, *, scopes=("spatial.view", "spatial.control", "spatial.presence", "voice.spatial", "approvals.spatial"),
                        name="Test iPhone", device_type="phone", requested=None, capabilities=("touch", "display")):
    key = DeviceKey()
    code = hub.create_pairing_code(scopes, "test")["code"]
    paired = hub.pair(code, name, device_type, key.jwk())
    device_id = paired["device"]["id"]
    nonce = hub.challenge(device_id)["nonce"]
    welcome = await hub.open_session(device_id, nonce=nonce, signature=key.proof(device_id, nonce, requested),
                                     requested=requested, capabilities=list(capabilities), client={"app": "test"})
    session = hub.sessions.get(welcome["session_id"])
    return key, device_id, session, welcome


def drain(session) -> List[Dict[str, Any]]:
    messages, _ = session.outbox.after(session.outbox.acked)
    if messages:
        session.outbox.ack(messages[-1]["sseq"])
    return messages


def temporary_root(test) -> Path:
    directory = tempfile.TemporaryDirectory()
    test.addCleanup(directory.cleanup)
    return Path(directory.name)


def dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))
