"""Device keys and the challenge-response session handshake.

A remote presence device generates a P-256 key pair on the device (WebCrypto,
non-extractable private key) and registers only the public key when it pairs.
To open a session it asks Core for a single-use nonce and signs

    akashi.remote.session/1 \\n <device_id> \\n <nonce> \\n <requested scopes or *>

with ECDSA/SHA-256. A captured proof cannot be replayed (the nonce is consumed
on first use and expires after 60 s) and cannot be re-targeted to other scopes
(they are part of the signed message). No long-lived secret ever travels after
pairing.

Devices that cannot use WebCrypto (an insecure browser context) may pair with a
bearer device secret instead; that mode is weaker, labelled as such, and uses
the existing salted-hash storage of the device registry.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

PROOF_PREFIX = "akashi.remote.session/1"
NONCE_TTL_SECONDS = 60.0
MAX_NONCES = 512
MAX_NONCES_PER_DEVICE = 4


class IdentityError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _b64url_decode(value: str, expected: Optional[int] = None) -> bytes:
    if not isinstance(value, str) or len(value) > 200 or not all(c.isalnum() or c in "-_" for c in value):
        raise IdentityError("bad_encoding", "Value is not base64url.")
    raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if expected is not None and len(raw) != expected:
        raise IdentityError("bad_encoding", "Value has the wrong length.")
    return raw


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def normalize_public_jwk(jwk: Any) -> Dict[str, str]:
    """Accept only an EC P-256 public JWK; private members are refused outright."""
    if not isinstance(jwk, dict):
        raise IdentityError("bad_key", "Public key must be a JWK object.")
    if "d" in jwk:
        raise IdentityError("bad_key", "A private key was sent; only the public key may leave the device.")
    if jwk.get("kty") != "EC" or jwk.get("crv") != "P-256":
        raise IdentityError("bad_key", "Only EC P-256 device keys are supported.")
    x = _b64url_decode(jwk.get("x", ""), 32)
    y = _b64url_decode(jwk.get("y", ""), 32)
    try:
        ec.EllipticCurvePublicNumbers(int.from_bytes(x, "big"), int.from_bytes(y, "big"), ec.SECP256R1()).public_key()
    except ValueError as exc:
        raise IdentityError("bad_key", "Public key is not a point on P-256.") from exc
    return {"kty": "EC", "crv": "P-256", "x": _b64url(x), "y": _b64url(y)}


def key_id(jwk: Dict[str, str]) -> str:
    """RFC 7638 JWK thumbprint (base64url SHA-256)."""
    canonical = json.dumps({"crv": jwk["crv"], "kty": jwk["kty"], "x": jwk["x"], "y": jwk["y"]}, separators=(",", ":"), sort_keys=True)
    return _b64url(hashlib.sha256(canonical.encode("utf-8")).digest())


def proof_message(device_id: str, nonce: str, scopes: Optional[Iterable[str]]) -> bytes:
    requested = "*" if scopes is None else ",".join(sorted(set(scopes))) or "-"
    return f"{PROOF_PREFIX}\n{device_id}\n{nonce}\n{requested}".encode("utf-8")


def verify(jwk: Dict[str, str], message: bytes, signature: str) -> bool:
    """Verify a WebCrypto ECDSA P-256/SHA-256 signature (IEEE P1363 r||s, base64url)."""
    try:
        raw = _b64url_decode(signature, 64)
    except IdentityError:
        return False
    key = ec.EllipticCurvePublicNumbers(int.from_bytes(_b64url_decode(jwk["x"], 32), "big"),
                                        int.from_bytes(_b64url_decode(jwk["y"], 32), "big"), ec.SECP256R1()).public_key()
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    try:
        key.verify(der, message, ec.ECDSA(hashes.SHA256()))
        return True
    except InvalidSignature:
        return False


@dataclass
class _Nonce:
    device_id: str
    expires: float


class ChallengeStore:
    """Single-use, short-lived nonces bound to one device."""

    def __init__(self, monotonic: Callable[[], float] = time.monotonic, ttl: float = NONCE_TTL_SECONDS) -> None:
        self._nonces: Dict[str, _Nonce] = {}
        self._lock = threading.Lock()
        self._monotonic = monotonic
        self.ttl = ttl

    def _expire(self, now: float) -> None:
        for key in [k for k, v in self._nonces.items() if v.expires <= now]:
            del self._nonces[key]

    def issue(self, device_id: str) -> Dict[str, Any]:
        now = self._monotonic()
        with self._lock:
            self._expire(now)
            mine = sorted((k for k, v in self._nonces.items() if v.device_id == device_id), key=lambda k: self._nonces[k].expires)
            while len(mine) >= MAX_NONCES_PER_DEVICE:
                del self._nonces[mine.pop(0)]
            if len(self._nonces) >= MAX_NONCES:
                raise IdentityError("busy", "Too many pending handshakes. Try again shortly.")
            nonce = secrets.token_urlsafe(24)
            self._nonces[nonce] = _Nonce(device_id, now + self.ttl)
        return {"nonce": nonce, "expires_in": self.ttl}

    def consume(self, nonce: str, device_id: str) -> None:
        now = self._monotonic()
        with self._lock:
            self._expire(now)
            entry = self._nonces.pop(nonce, None) if isinstance(nonce, str) else None
        if entry is None:
            raise IdentityError("nonce_invalid", "The handshake challenge is unknown, used or expired. Request a new one.")
        if entry.device_id != device_id:
            raise IdentityError("nonce_invalid", "The handshake challenge belongs to another device.")
