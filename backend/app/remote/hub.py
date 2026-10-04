"""RemoteHub: secure device sessions and message dispatch for AKASHI's thin clients.

Transport-independent. WebSocket and HTTP long-poll adapters (``app.api.remote``)
both call ``receive`` with raw envelopes and drain each session's outbox.

Receive pipeline for one envelope:

1. size / JSON / envelope validation               → ``bad_envelope``
2. session liveness (closed, expired, revoked)     → ``session_*``
3. owner-side device changes applied (grants, revocation) before anything else
4. kind lookup                                     → ``unknown_kind``
5. scope check against the session's *current* scopes → ``forbidden`` (audited)
6. rate limit per message class                    → ``rate_limited`` (not consumed)
7. delivery rules
   * reliable: repeated ``id`` → cached response, never re-applied;
     ``seq`` ≤ last processed → ``out_of_order``, never applied
   * realtime: ``seq`` ≤ newest of that kind → superseded (dropped);
     age beyond the kind's budget → ``stale_input`` (dropped)
8. handler → ``ack`` (cached for idempotency) or ``error``

Consumers (Spatial Lab, approvals, voice) register kinds with the scopes they
need and subscribe to session lifecycle events to release what a departing or
demoted device was holding.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, FrozenSet, Iterable, List, Optional, Set

from app.devices.store import DeviceStore
from app.remote import capabilities as caps
from app.remote import identity, protocol, scopes
from app.remote.audit import AuditLog, AuditUnavailable
from app.remote.flow import TokenBucket
from app.remote.sessions import RemoteSession, SessionAuthError, SessionConfig, SessionManager

Handler = Callable[["MessageContext"], Awaitable[Optional[Dict[str, Any]]]]
Listener = Callable[[RemoteSession], Any]


class RemoteError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 400, details: Optional[Dict[str, Any]] = None,
                 retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.details = details
        self.retryable = retryable


@dataclass(frozen=True)
class KindSpec:
    kind: str
    handler: Handler
    delivery: str  # "reliable" | "realtime"
    any_of: FrozenSet[str]  # session needs at least one; empty = any authenticated session
    rate_class: str
    max_age_ms: Optional[float]
    owner_only: bool = False


@dataclass
class MessageContext:
    hub: "RemoteHub"
    session: RemoteSession
    envelope: protocol.Envelope
    received_ms: float
    age_ms: float
    transport: str

    def provenance(self, modality: str) -> Dict[str, Any]:
        """Who/what/when for history and audit: enough to answer 'why did this change?'."""
        return {
            "device_id": str(self.session.device.get("id")),
            "device_name": str(self.session.device.get("name") or "Remote device")[:100],
            "device_type": str(self.session.device.get("device_type") or "unknown")[:40],
            "session": self.session.id,
            "session_kind": self.session.kind,
            "modality": modality,
            "message_id": self.envelope.id,
            "seq": self.envelope.seq,
            "sent_at_ms": round(self.envelope.t, 3),
            "received_at": datetime.fromtimestamp(self.received_ms / 1000, timezone.utc).isoformat(),
            "transport": self.transport,
        }


@dataclass
class HandshakeLimits:
    per_device: Dict[str, TokenBucket] = field(default_factory=dict)
    overall: TokenBucket = field(default_factory=lambda: TokenBucket(1.0, 30.0))


class RemoteHub:
    def __init__(self, devices: DeviceStore, *, audit: Optional[AuditLog] = None, config: SessionConfig = SessionConfig(),
                 monotonic: Callable[[], float] = time.monotonic, wall_ms: Callable[[], float] = lambda: time.time() * 1000,
                 endpoints: Iterable[str] = (), owner_label: str = "AKASHI primary") -> None:
        self.devices = devices
        self.audit = audit or AuditLog(None)
        self.monotonic = monotonic
        self.wall_ms = wall_ms
        self.sessions = SessionManager(config, monotonic, wall_ms)
        self.challenges = identity.ChallengeStore(monotonic)
        self.registry = caps.CapabilityRegistry(self.sessions.live, monotonic)
        self.endpoints = tuple(endpoints)
        self.owner_label = owner_label
        self.kinds: Dict[str, KindSpec] = {}
        self.channels: Dict[str, Set[str]] = {}
        self.listeners: Dict[str, List[Listener]] = {"opened": [], "closed": [], "stale": [], "resumed": [], "scopes": [],
                                                     "capabilities": []}
        self._device_version = devices.version
        self._limits = HandshakeLimits()
        self.counters: Dict[str, int] = {}
        self._register_builtins()

    # Registration -----------------------------------------------------------------
    def register(self, kind: str, handler: Handler, *, delivery: str = "reliable", any_of: Iterable[str] = (),
                 rate_class: Optional[str] = None, max_age_ms: Optional[float] = None, owner_only: bool = False) -> None:
        if kind in self.kinds or not protocol.KIND_PATTERN.match(kind):
            raise ValueError(f"Remote kind '{kind}' is invalid or already registered.")
        if delivery not in {"reliable", "realtime"}:
            raise ValueError("delivery must be reliable or realtime")
        needed = frozenset(any_of)
        unknown = needed - set(scopes.SCOPES)
        if unknown:
            raise ValueError(f"Unknown scopes for {kind}: {sorted(unknown)}")
        self.kinds[kind] = KindSpec(kind, handler, delivery, needed, rate_class or delivery, max_age_ms, owner_only)

    def on(self, event: str, listener: Listener) -> None:
        self.listeners[event].append(listener)

    async def _emit(self, event: str, session: RemoteSession) -> None:
        for listener in self.listeners[event]:
            result = listener(session)
            if inspect.isawaitable(result):
                await result

    def _count(self, key: str) -> None:
        self.counters[key] = self.counters.get(key, 0) + 1

    # Pairing ----------------------------------------------------------------------
    def create_pairing_code(self, granted: Iterable[str], label: Optional[str] = None) -> Dict[str, Any]:
        self.audit.require()
        normalized = scopes.normalize(granted)
        if not normalized:
            raise RemoteError("no_scopes", "Choose at least one permission for the device.")
        code = self.devices.create_pairing_code("presence", sorted(normalized), label)
        self.audit.record("pairing.code_created", by={"kind": "owner"}, scopes=sorted(normalized), label=label,
                          expires_at=code["expires_at"])
        return {**code, "scopes": sorted(normalized), "protocol": protocol.PROTOCOL, "endpoints": list(self.endpoints)}

    def pair(self, code: str, name: str, device_type: str, public_key: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        self.audit.require()
        jwk = kid = None
        if public_key is not None:
            try:
                jwk = identity.normalize_public_jwk(public_key)
            except identity.IdentityError as exc:
                raise RemoteError(exc.code, str(exc)) from exc
            kid = identity.key_id(jwk)
        try:
            device, secret = self.devices.pair(code, name, device_type, [], public_key=jwk, key_id=kid, expected_role="presence")
        except PermissionError as exc:
            self.audit.record_limited("pair-refused", 10.0, "pairing.refused", reason=str(exc)[:200])
            raise RemoteError("pairing_refused", str(exc), status=401) from exc
        self.audit.record("device.paired", device=self._device_summary(device), credential=device.get("credential"),
                          key_id=kid, scopes=device.get("grants", []))
        result: Dict[str, Any] = {"device": device, "protocol": protocol.PROTOCOL, "endpoints": list(self.endpoints)}
        if secret is not None:
            result["device_secret"] = secret
        return result

    @staticmethod
    def _device_summary(device: Dict[str, Any]) -> Dict[str, Any]:
        return {"id": device.get("id"), "name": device.get("name"), "device_type": device.get("device_type")}

    # Handshake --------------------------------------------------------------------
    def _limit_handshake(self, device_id: str) -> None:
        now = self.monotonic()
        bucket = self._limits.per_device.setdefault(str(device_id)[:128], TokenBucket(0.5, 10.0))
        if len(self._limits.per_device) > 2048:
            self._limits.per_device.clear()
        if not self._limits.overall.allow(now) or not bucket.allow(now):
            raise RemoteError("rate_limited", "Too many handshakes. Wait a moment.", status=429, retryable=True)

    def challenge(self, device_id: str) -> Dict[str, Any]:
        self._limit_handshake(device_id)
        if self.devices.presence_credential(device_id) is None:
            self.audit.record_limited("challenge-unknown", 10.0, "session.refused", reason="device_unknown")
            raise RemoteError("device_unknown", "Unknown or revoked device. Pair again.", status=401)
        try:
            return self.challenges.issue(device_id)
        except identity.IdentityError as exc:
            raise RemoteError(exc.code, str(exc), status=429, retryable=True) from exc

    async def open_session(self, device_id: str, *, nonce: Optional[str] = None, signature: Optional[str] = None,
                           secret: Optional[str] = None, requested: Optional[Iterable[str]] = None,
                           client: Optional[Dict[str, Any]] = None, capabilities: Iterable[Any] = (),
                           transport: Optional[str] = None) -> Dict[str, Any]:
        self._limit_handshake(device_id)
        self.audit.require()
        credential = self.devices.presence_credential(device_id)
        if credential is None:
            self.audit.record_limited(f"refused:{str(device_id)[:64]}", 10.0, "session.refused", device_id=str(device_id)[:64],
                                      reason="device_unknown")
            raise RemoteError("device_unknown", "Unknown or revoked device. Pair again.", status=401)
        requested_set = None if requested is None else frozenset(requested)
        if requested_set is not None:
            unknown = requested_set - set(scopes.SCOPES)
            if unknown:
                raise RemoteError("bad_scopes", f"Unknown scopes requested: {sorted(unknown)[:5]}")
        device = credential["device"]
        if credential["credential"] == "key":
            if not nonce or not signature:
                raise RemoteError("proof_required", "This device must sign a handshake challenge.", status=401)
            try:
                self.challenges.consume(nonce, device_id)
            except identity.IdentityError as exc:
                self.audit.record_limited(f"refused:{device_id}", 10.0, "session.refused", device=self._device_summary(device),
                                          reason=exc.code)
                raise RemoteError(exc.code, str(exc), status=401) from exc
            if not identity.verify(credential["public_key"], identity.proof_message(device_id, nonce, requested_set), signature):
                self.audit.record_limited(f"refused:{device_id}", 10.0, "session.refused", device=self._device_summary(device),
                                          reason="signature_invalid")
                raise RemoteError("signature_invalid", "The handshake signature is not valid for this device.", status=401)
        else:
            if not secret or self.devices.authenticate(device_id, secret, touch=False) is None:
                self.audit.record_limited(f"refused:{device_id}", 10.0, "session.refused", device=self._device_summary(device),
                                          reason="secret_invalid")
                raise RemoteError("secret_invalid", "Invalid device credential.", status=401)
        granted = scopes.effective(requested_set, device.get("grants", []))
        if not granted:
            raise RemoteError("no_scopes", "The owner has not granted this device any permission.", status=403)
        try:
            parsed = caps.parse(capabilities)
        except caps.CapabilityError as exc:
            raise RemoteError("bad_capabilities", str(exc)) from exc
        self.devices.touch(device_id)
        session, token, replaced = self.sessions.open("device", self._device_summary(device), granted, requested_set,
                                                      _clean_client(client), parsed)
        session.transport = transport
        for old in replaced:
            await self._closed(old)
        self.audit.record("session.opened", device=self._device_summary(device), session=session.id, scopes=sorted(granted),
                          client=session.client, credential=credential["credential"], capabilities=sorted(parsed))
        await self._emit("opened", session)
        return self._welcome(session, token)

    async def open_owner_session(self, label: Optional[str] = None, client: Optional[Dict[str, Any]] = None,
                                 capabilities: Iterable[Any] = ()) -> Dict[str, Any]:
        """A session for the owner's own UI (authenticated by the API token at the transport)."""
        self.audit.require()
        try:
            parsed = caps.parse(capabilities)
        except caps.CapabilityError as exc:
            raise RemoteError("bad_capabilities", str(exc)) from exc
        device = {"id": "owner", "name": (label or self.owner_label)[:100], "device_type": "primary"}
        session, token, replaced = self.sessions.open("owner", device, scopes.OWNER_SCOPES, None, _clean_client(client), parsed)
        for old in replaced:
            await self._closed(old)
        self.audit.record("session.opened", device=device, session=session.id, scopes=["owner"], client=session.client)
        await self._emit("opened", session)
        return self._welcome(session, token)

    def _welcome(self, session: RemoteSession, token: str) -> Dict[str, Any]:
        return {"session_id": session.id, "session_token": token, "kind": session.kind, "device": session.device_public(),
                "scopes": sorted(session.scopes), "protocol": protocol.PROTOCOL, "server_time_ms": self.wall_ms(),
                **self.sessions.config.public(), "endpoints": list(self.endpoints),
                "limits": {"max_message_bytes": protocol.MAX_MESSAGE_BYTES, "max_batch": protocol.MAX_BATCH}}

    # Authentication at the transport ----------------------------------------------
    def authenticate(self, session_id: str, token: Optional[str], *, owner_token_valid: bool = False) -> RemoteSession:
        if owner_token_valid:
            session = self.sessions.get(session_id)
            if session.kind != "owner":
                raise SessionAuthError("session_invalid", "The API token only authenticates owner sessions.")
            return self.sessions.check_live(session)
        return self.sessions.authenticate(session_id, token)

    # Receive ----------------------------------------------------------------------
    async def receive(self, session: RemoteSession, raw: Any, transport: str = "unknown") -> Optional[Dict[str, Any]]:
        received_ms = self.wall_ms()
        try:
            envelope = protocol.parse(raw)
        except protocol.ProtocolError as exc:
            session.count("bad_envelope")
            return protocol.error(exc.code, str(exc))
        await self.refresh_devices()
        try:
            self.sessions.check_live(session)
        except SessionAuthError as exc:
            await self._closed(session)
            return protocol.error(exc.code, str(exc), re_id=envelope.id, seq=envelope.seq)
        session.transport = transport
        if self.sessions.touch(session):
            await self._emit("resumed", session)
        age = session.clock.observe(envelope.t, received_ms)
        spec = self.kinds.get(envelope.kind)
        if spec is None:
            session.count("unknown_kind")
            return protocol.error("unknown_kind", f"Unknown message kind '{envelope.kind}'.", re_id=envelope.id, seq=envelope.seq)
        if (spec.owner_only and session.kind != "owner") or (spec.any_of and not spec.any_of & session.scopes):
            session.count("forbidden")
            self.audit.record_limited(f"forbidden:{session.id}:{spec.kind}", 60.0, "message.forbidden", session=session.id,
                                      device=session.device_public(), message_kind=spec.kind, scopes=sorted(session.scopes))
            return protocol.error("forbidden", f"This device is not permitted to use '{spec.kind}'.", re_id=envelope.id,
                                  seq=envelope.seq, details={"needs_any_of": sorted(spec.any_of)})
        if spec.delivery == "reliable" and envelope.id in session.results:
            session.count("duplicate")
            cached = dict(session.results[envelope.id])
            return {**cached, "duplicate": True}
        if not session.bucket(spec.rate_class).allow(self.monotonic()):
            session.count("rate_limited")
            if spec.delivery == "realtime" and spec.kind != "ping":
                return None
            return protocol.error("rate_limited", "Too many messages; slow down.", re_id=envelope.id, seq=envelope.seq,
                                  retryable=True)
        if spec.delivery == "reliable":
            if envelope.seq <= session.reliable_seq:
                session.count("out_of_order")
                return protocol.error("out_of_order", "This message is older than one already processed; it was not applied.",
                                      re_id=envelope.id, seq=envelope.seq, details={"last_processed_seq": session.reliable_seq})
        else:
            newest = session.realtime_seq.get(spec.kind, 0)
            if envelope.seq <= newest:
                session.count("superseded")
                return None
            if spec.max_age_ms is not None and session.clock.late(age, spec.max_age_ms):
                session.count("stale_input")
                session.realtime_seq[spec.kind] = envelope.seq
                return None
            session.realtime_seq[spec.kind] = envelope.seq
        context = MessageContext(self, session, envelope, received_ms, age, transport)
        try:
            body = await spec.handler(context)
            response = None if spec.delivery == "realtime" and body is None else protocol.ack(envelope, body)
        except RemoteError as exc:
            response = protocol.error(exc.code, str(exc), re_id=envelope.id, seq=envelope.seq, details=exc.details,
                                      retryable=exc.retryable)
        except AuditUnavailable as exc:
            response = protocol.error("audit_unavailable", str(exc), re_id=envelope.id, seq=envelope.seq)
        if spec.delivery == "reliable":
            session.reliable_seq = envelope.seq
            if response is not None and not (response["kind"] == "error" and response["body"].get("retryable")):
                session.remember(envelope.id, response)
        session.count(f"kind:{spec.kind}")
        return response

    async def receive_batch(self, session: RemoteSession, messages: List[Any], transport: str) -> List[Dict[str, Any]]:
        if len(messages) > protocol.MAX_BATCH:
            return [protocol.error("too_large", f"At most {protocol.MAX_BATCH} messages per batch.")]
        responses = []
        for raw in messages:
            response = await self.receive(session, raw, transport)
            if response is not None:
                responses.append(response)
        return responses

    # Channels ---------------------------------------------------------------------
    def subscribe(self, session: RemoteSession, channel: str) -> None:
        self.channels.setdefault(channel, set()).add(session.id)
        session.channels.add(channel)

    def unsubscribe(self, session: RemoteSession, channel: str) -> None:
        self.channels.get(channel, set()).discard(session.id)
        session.channels.discard(channel)

    def members(self, channel: str) -> List[RemoteSession]:
        result = []
        for session_id in list(self.channels.get(channel, ())):
            session = self.sessions.sessions.get(session_id)
            if session is None or session.state == "closed":
                self.channels[channel].discard(session_id)
                continue
            result.append(session)
        return result

    def publish(self, channel: str, kind: str, body: Dict[str, Any], *, exclude: Optional[str] = None,
                coalesce: Optional[str] = None, require: Optional[FrozenSet[str]] = None) -> int:
        delivered = 0
        for session in self.members(channel):
            if session.id == exclude or (require and not require & session.scopes):
                continue
            session.outbox.push(kind, body, coalesce=coalesce)
            delivered += 1
        return delivered

    # Lifecycle --------------------------------------------------------------------
    async def sweep(self) -> None:
        await self.refresh_devices()
        for session, transition in self.sessions.sweep():
            if transition == "stale":
                session.outbox.push("session.stale", {"reason": "no traffic"})
                await self._emit("stale", session)
            else:
                await self._closed(session)

    async def _closed(self, session: RemoteSession) -> None:
        for channel in list(session.channels):
            self.unsubscribe(session, channel)
        if not session.data.get("close_audited"):
            session.data["close_audited"] = True
            try:
                self.audit.record("session.closed", session=session.id, device=session.device_public(), reason=session.close_reason)
            except AuditUnavailable:
                pass
            await self._emit("closed", session)
        session.outbox.wake_all()

    async def close_session(self, session: RemoteSession, reason: str) -> None:
        if self.sessions.close(session, reason):
            await self._closed(session)

    async def revoke_device(self, device_id: str, by: Optional[Dict[str, Any]] = None) -> int:
        """Revocation takes effect for live sessions before this returns."""
        closed = 0
        for session in self.sessions.for_device(device_id):
            session.outbox.push("revoked", {"reason": "The owner revoked this device."})
            if self.sessions.close(session, "revoked"):
                closed += 1
                await self._closed(session)
        self._device_version = self.devices.version
        return closed

    async def refresh_devices(self) -> None:
        """Apply owner-side device changes (revocation, grants) to live sessions immediately."""
        if self.devices.version == self._device_version:
            return
        self._device_version = self.devices.version
        for session in self.sessions.live():
            if session.kind != "device":
                continue
            record = self.devices.get(str(session.device.get("id")))
            if record is None or record.get("revoked"):
                session.outbox.push("revoked", {"reason": "The owner revoked this device."})
                self.sessions.close(session, "revoked")
                await self._closed(session)
                continue
            updated = scopes.effective(session.requested, record.get("grants", []))
            if updated != session.scopes:
                lost = sorted(session.scopes - updated)
                session.scopes = updated
                session.outbox.push("session.updated", {"scopes": sorted(updated), "lost": lost})
                await self._emit("scopes", session)

    async def set_grants(self, device_id: str, granted: Iterable[str]) -> Dict[str, Any]:
        self.audit.require()
        normalized = scopes.normalize(granted)
        device = self.devices.set_grants(device_id, sorted(normalized))
        self.audit.record("device.grants_changed", by={"kind": "owner"}, device=self._device_summary(device), scopes=sorted(normalized))
        await self.refresh_devices()
        return device

    async def update_capabilities(self, session: RemoteSession, items: Iterable[Any]) -> None:
        try:
            session.capabilities = caps.parse(items)
        except caps.CapabilityError as exc:
            raise RemoteError("bad_capabilities", str(exc)) from exc
        await self._emit("capabilities", session)

    # Introspection ----------------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        now = self.monotonic()
        return {"protocol": protocol.PROTOCOL, "endpoints": list(self.endpoints), "config": self.sessions.config.public(),
                "sessions": [s.public(now) for s in self.sessions.live()], "counters": dict(self.counters),
                "audit": {"available": self.audit.broken is None, "reason": self.audit.broken}}

    # Built-in kinds ----------------------------------------------------------------
    def _register_builtins(self) -> None:
        async def ping(ctx: MessageContext) -> Dict[str, Any]:
            cursor = ctx.envelope.body.get("ack")
            if isinstance(cursor, int) and not isinstance(cursor, bool):
                ctx.session.outbox.ack(cursor)
            return {"server_ms": ctx.received_ms, "echo_t": ctx.envelope.t, "age_ms": round(ctx.age_ms, 1),
                    "state": ctx.session.state}

        async def capabilities_update(ctx: MessageContext) -> Dict[str, Any]:
            items = ctx.envelope.body.get("capabilities")
            if not isinstance(items, list):
                raise RemoteError("bad_capabilities", "capabilities must be a list.")
            await self.update_capabilities(ctx.session, items)
            return {"capabilities": [c.public() for c in ctx.session.capabilities.values()]}

        async def close(ctx: MessageContext) -> Dict[str, Any]:
            await self.close_session(ctx.session, "client")
            return {"closed": True}

        async def providers(ctx: MessageContext) -> Dict[str, Any]:
            capability = ctx.envelope.body.get("capability")
            try:
                if capability is None:
                    return {"devices": self.registry.summary()}
                return {"providers": [p.public() for p in self.registry.providers(str(capability))]}
            except caps.CapabilityError as exc:
                raise RemoteError("bad_capabilities", str(exc)) from exc

        self.register("ping", ping, delivery="realtime", rate_class="realtime")
        self.register("capabilities.update", capabilities_update, rate_class="control")
        self.register("session.close", close, rate_class="control")
        self.register("devices.providers", providers, owner_only=True)


def _clean_client(client: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    client = client if isinstance(client, dict) else {}
    result = {}
    for key in ("app", "version", "platform", "shell", "user_agent"):
        value = client.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value.strip()[:120]
    return result
