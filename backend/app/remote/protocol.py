"""Wire protocol ``akashi.remote/1`` (transport-independent).

Client → Core envelope::

    {"v": 1, "id": "<8-64 url-safe chars>", "seq": <int>, "t": <client ms>, "kind": "<kind>", "body": {...}}

* ``id``  — idempotency key. A repeated id gets the cached response and is
  never applied twice.
* ``seq`` — strictly increasing per session (one counter for all kinds; gaps
  are normal). Reliable kinds with ``seq`` ≤ the last processed one are
  rejected as ``out_of_order`` (never applied); realtime kinds older than the
  newest of their kind are silently superseded.
* ``t``   — the client's own clock; only used to measure relative delay
  (``app.remote.flow.ClockEstimator``), never trusted as absolute time.

Core → client::

    {"v": 1, "sseq": <int>, "kind": "<kind>", "body": {...}}      pushed (outbox)
    {"v": 1, "kind": "ack" | "error", "re": "<id>", "seq": <int>, "body": {...}}   direct reply

``sseq`` is monotonic but not contiguous (superseded lossy messages are
dropped). Scene state is never inferred from ``sseq``: consumers carry their
own authoritative cursor (Spatial Lab uses the history revision).
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Union

PROTOCOL = "akashi.remote/1"
VERSION = 1
MAX_MESSAGE_BYTES = 64 * 1024
MAX_BATCH = 32
MAX_SEQ = 2 ** 53
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
KIND_PATTERN = re.compile(r"^[a-z][a-z0-9_.]{1,47}$")


class ProtocolError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Envelope:
    id: str
    seq: int
    t: float
    kind: str
    body: Dict[str, Any]


def parse(raw: Union[str, bytes, Dict[str, Any]]) -> Envelope:
    if isinstance(raw, (str, bytes)):
        if len(raw) > MAX_MESSAGE_BYTES:
            raise ProtocolError("too_large", f"Messages are limited to {MAX_MESSAGE_BYTES} bytes.")
        try:
            raw = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ProtocolError("bad_envelope", "Message is not JSON.") from exc
    if not isinstance(raw, dict):
        raise ProtocolError("bad_envelope", "Message must be a JSON object.")
    if raw.get("v") != VERSION:
        raise ProtocolError("bad_version", f"Unsupported protocol version; this Core speaks {PROTOCOL}.")
    message_id, seq, sent, kind, body = raw.get("id"), raw.get("seq"), raw.get("t"), raw.get("kind"), raw.get("body", {})
    if not isinstance(message_id, str) or not ID_PATTERN.match(message_id):
        raise ProtocolError("bad_envelope", "Message id must be 8-64 URL-safe characters.")
    if isinstance(seq, bool) or not isinstance(seq, int) or not 1 <= seq <= MAX_SEQ:
        raise ProtocolError("bad_envelope", "Message seq must be a positive integer.")
    if isinstance(sent, bool) or not isinstance(sent, (int, float)) or not math.isfinite(sent) or sent < 0:
        raise ProtocolError("bad_envelope", "Message t must be a finite, non-negative client timestamp.")
    if not isinstance(kind, str) or not KIND_PATTERN.match(kind):
        raise ProtocolError("bad_envelope", "Message kind is malformed.")
    if not isinstance(body, dict):
        raise ProtocolError("bad_envelope", "Message body must be an object.")
    return Envelope(message_id, seq, float(sent), kind, body)


def ack(envelope: Envelope, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"v": VERSION, "kind": "ack", "re": envelope.id, "seq": envelope.seq, "body": body or {}}


def error(code: str, message: str, *, re_id: Optional[str] = None, seq: Optional[int] = None,
          details: Optional[Dict[str, Any]] = None, retryable: bool = False) -> Dict[str, Any]:
    body: Dict[str, Any] = {"code": code, "message": message[:300], "retryable": retryable}
    if details:
        body["details"] = details
    message_out: Dict[str, Any] = {"v": VERSION, "kind": "error", "body": body}
    if re_id is not None:
        message_out["re"] = re_id
    if seq is not None:
        message_out["seq"] = seq
    return message_out
