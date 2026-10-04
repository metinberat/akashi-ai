"""Spatial Lab over remote presence: the first consumer of ``app.remote``.

Core stays authoritative. A remote device never sends state; it sends the same
requests every other input sends, with its provenance attached by Core:

    device input → envelope → RemoteHub (auth, scope, order, dedupe, staleness)
      → this bridge → SpatialLabService.submit(..., base_revision, lease_owner)
      → ActionHistory event (origin.kind = "remote", origin.remote = device/session/message)
      → ordered fan-out of the event (with its patches) to every subscribed viewer

Synchronization uses the scene history revision as the only cursor. A client
that reconnects sends the revision (and digest) it holds; it receives the
missing events when its copy is provably identical at that revision, otherwise a
full snapshot. ``sseq`` gaps never matter for scene state.

Live manipulation: a device that holds a lease streams ``spatial.preview``
transforms (lossy, coalesced, never recorded) so other viewers see the object
move; the single committed transform at release is the only history entry.
When the device goes silent, leaves, loses ``spatial.control`` or is revoked,
its leases and previews are released at once: every viewer snaps back to the
last committed (authoritative) transform.
"""

from __future__ import annotations

import math
import threading
from typing import Any, Dict, List, Optional

from app.history.engine import CommandRejected
from app.remote.hub import MessageContext, RemoteError, RemoteHub
from app.remote.sessions import RemoteSession
from app.spatial.assets import AssetError
from app.spatial.form_library import FormLibraryError
from app.spatial.model import LIMITS
from app.spatial.references import Clarification
from app.spatial.replies import describe_origin
from app.spatial.service import RequestInvalid, SpatialLabService
from app.spatial.session import ANCHORS, SessionCorrupted

MODALITIES = {"gesture", "touch", "pointer", "language", "voice", "ui"}
MAX_EVENTS_INLINE = 200
PREVIEW_MAX_AGE_MS = 400.0
PRESENCE_MAX_AGE_MS = 1000.0
RENEW_MAX_AGE_MS = 1500.0


def channel(session_id: str) -> str:
    return f"spatial:{session_id}"


def compact_event(event: Dict[str, Any]) -> Dict[str, Any]:
    return {"seq": event["seq"], "kind": event["kind"], "category": event.get("category"), "at": event["at"],
            "command": event["command"].get("type"), "targets": event.get("targets", []), "summary": event.get("summary"),
            "patches": event["patches"], "digest_before": event["digest_before"], "digest_after": event["digest_after"],
            "undoes": event.get("undoes"), "redoes": event.get("redoes"), "origin": describe_origin(event.get("origin", {}))}


def _finite(values: Any, size: int) -> bool:
    return isinstance(values, list) and len(values) == size and all(
        isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values)


def valid_transform(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict) or not _finite(value.get("position"), 3) or not _finite(value.get("rotation"), 4):
        raise RemoteError("bad_transform", "A transform needs a finite position[3] and rotation[4].")
    scale = value.get("scale")
    if isinstance(scale, bool) or not isinstance(scale, (int, float)) or not math.isfinite(scale):
        raise RemoteError("bad_transform", "A transform needs a finite scale.")
    lo, hi = LIMITS["position_min"], LIMITS["position_max"]
    if not all(lo[i] - 1e-6 <= value["position"][i] <= hi[i] + 1e-6 for i in range(3)):
        raise RemoteError("bad_transform", "Position is outside the scene limits.")
    if not LIMITS["scale_min"] - 1e-9 <= scale <= LIMITS["scale_max"] + 1e-9:
        raise RemoteError("bad_transform", "Scale is outside the scene limits.")
    norm = math.sqrt(sum(v * v for v in value["rotation"]))
    if not 0.9 <= norm <= 1.1:
        raise RemoteError("bad_transform", "Rotation must be a unit quaternion.")
    return {"position": [round(float(v), 4) for v in value["position"]],
            "rotation": [round(float(v) / norm, 6) for v in value["rotation"]], "scale": round(float(scale), 5)}


def _clean_input(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed: Dict[str, Any] = {}
    for key, item in list(value.items())[:24]:
        if not isinstance(key, str) or len(key) > 40:
            continue
        if isinstance(item, (bool, int)):
            allowed[key] = item
        elif isinstance(item, float) and math.isfinite(item):
            allowed[key] = round(item, 6)
        elif isinstance(item, str):
            allowed[key] = item[:200]
    return allowed


class SpatialRemoteBridge:
    def __init__(self, service: SpatialLabService, hub: RemoteHub) -> None:
        self.service = service
        self.hub = hub
        self.previews: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self.cursors: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self.published: Dict[str, int] = {}
        self._lock = threading.RLock()
        service.observe(self._on_change)
        hub.on("closed", self._session_left)
        hub.on("stale", self._session_left)
        hub.on("scopes", self._scopes_changed)
        hub.on("capabilities", self._roster_changed)
        hub.on("resumed", self._roster_changed)
        self._register()

    # Helpers ------------------------------------------------------------------------
    def _subscribed(self, session: RemoteSession) -> str:
        spatial_id = session.data.get("spatial")
        if not spatial_id or channel(spatial_id) not in session.channels:
            raise RemoteError("not_subscribed", "Subscribe to a Spatial Lab session first.")
        return spatial_id

    def _origin(self, ctx: MessageContext, modality: str, provider_input: Any = None) -> Dict[str, Any]:
        if modality not in MODALITIES:
            raise RemoteError("bad_modality", f"Unknown input modality '{modality}'.")
        device_type = str(ctx.session.device.get("device_type") or "device")
        provider = "remote:" + "".join(c for c in device_type if c.isalnum() or c in "_-")[:40]
        return {"kind": "remote", "provider": provider or "remote:device", "interaction_id": ctx.envelope.id,
                "input": _clean_input(provider_input), "remote": ctx.provenance(modality)}

    @staticmethod
    def _fail(exc: Exception) -> RemoteError:
        if isinstance(exc, Clarification):
            return RemoteError(exc.code, exc.question, details={"kind": "clarification", "question": exc.question,
                                                               "candidates": exc.candidates})
        if isinstance(exc, CommandRejected):
            return RemoteError(exc.code, str(exc), details=getattr(exc, "details", None) or None)
        if isinstance(exc, SessionCorrupted):
            return RemoteError("session_corrupted", str(exc), status=423)
        if isinstance(exc, KeyError):
            return RemoteError("not_found", str(exc).strip("'\""), status=404)
        if isinstance(exc, RequestInvalid):
            return RemoteError("invalid_request", str(exc))
        code = getattr(exc, "code", "rejected")
        return RemoteError(str(code), str(exc))

    def holder(self, session: RemoteSession, modality: str) -> Dict[str, Any]:
        return {"device_id": session.device.get("id"), "device_name": session.device.get("name"),
                "device_type": session.device.get("device_type"), "session": session.id, "kind": session.kind,
                "modality": modality}

    def roster(self, spatial_id: str) -> List[Dict[str, Any]]:
        rows = []
        for member in self.hub.members(channel(spatial_id)):
            rows.append({"session": member.id, "device": member.device_public(), "state": member.state,
                         "scopes": sorted(member.scopes), "transport": member.transport,
                         "capabilities": [c.public() for c in member.capabilities.values()],
                         "cursors": list(self.cursors.get(spatial_id, {}).get(member.id, {}).get("cursors", []))})
        return rows

    def _digest_at(self, spatial_id: str, revision: int) -> Optional[str]:
        history = self.service.session(spatial_id).history
        if revision == history.revision:
            return history.digest()
        if 0 < revision < history.revision:
            return history.events[revision - 1]["digest_after"]
        if revision == 0:
            return history.events[0]["digest_before"] if history.events else history.digest()
        return None

    def sync_payload(self, spatial_id: str, revision: Optional[int], digest: Optional[str]) -> Dict[str, Any]:
        session = self.service.session(spatial_id)
        with session.lock:
            current = session.history.revision
            usable = (isinstance(revision, int) and not isinstance(revision, bool) and 0 <= revision <= current
                      and current - revision <= MAX_EVENTS_INLINE and digest is not None
                      and self._digest_at(spatial_id, revision) == digest)
            if usable:
                events = [compact_event(e) for e in session.history.events[revision:]]
                payload: Dict[str, Any] = {"mode": "events", "from_revision": revision, "events": events}
            else:
                payload = {"mode": "snapshot", "snapshot": self.service.snapshot(session)}
            payload.update(revision=current, digest=session.history.digest())
        payload["leases"] = self.service.leases(spatial_id)
        payload["previews"] = list(self.previews.get(spatial_id, {}).values())
        payload["roster"] = self.roster(spatial_id)
        payload["session"] = self.service.snapshot(session)["session"]
        return payload

    # Change fan-out -----------------------------------------------------------------
    def _on_change(self, spatial_id: str, change: Dict[str, Any]) -> None:
        kind = change.get("type")
        if kind == "events":
            events = change.get("events") or []
            self._publish_events(spatial_id, events[0]["seq"] if events else None)
        elif kind == "leases":
            self._publish_leases(spatial_id)
        elif kind == "confirmations":
            self._publish_session(spatial_id)

    def _publish_events(self, spatial_id: str, first_seq: Optional[int]) -> None:
        """Publish strictly in history order, whatever order the notifications arrive in."""
        with self._lock:
            session = self.service.session(spatial_id)
            with session.lock:
                start = self.published.get(spatial_id)
                if start is None:
                    start = max(0, (first_seq or session.history.revision) - 1)
                new = session.history.events[start:]
                revision = session.history.revision
                digest = session.history.digest()
                self.published[spatial_id] = revision
            if new:
                self.hub.publish(channel(spatial_id), "spatial.events",
                                 {"from_revision": start, "revision": revision, "digest": digest,
                                  "events": [compact_event(e) for e in new]})
        self._publish_session(spatial_id)

    def _publish_session(self, spatial_id: str) -> None:
        try:
            info = self.service.snapshot(self.service.session(spatial_id))["session"]
        except (KeyError, SessionCorrupted):
            return
        self.hub.publish(channel(spatial_id), "spatial.session", {"session": info}, coalesce=f"session:{spatial_id}")

    def _publish_leases(self, spatial_id: str) -> None:
        leases = self.service.leases(spatial_id)
        live = {lease["id"] for lease in leases}
        ended = []
        with self._lock:
            previews = self.previews.get(spatial_id, {})
            for lease_id in [k for k in previews if k not in live]:
                ended.append(previews.pop(lease_id))
        for preview in ended:
            self.hub.publish(channel(spatial_id), "spatial.preview",
                             {"lease_id": preview["lease_id"], "object_id": preview["object_id"], "ended": True},
                             coalesce=f"preview:{preview['lease_id']}")
        self.hub.publish(channel(spatial_id), "spatial.leases", {"leases": leases}, coalesce=f"leases:{spatial_id}")
        self._publish_session(spatial_id)

    def _publish_roster(self, spatial_id: str) -> None:
        self.hub.publish(channel(spatial_id), "spatial.roster", {"roster": self.roster(spatial_id)}, coalesce=f"roster:{spatial_id}")

    # Lifecycle ----------------------------------------------------------------------
    def _session_left(self, session: RemoteSession) -> None:
        """Disconnect, silence, revocation: release everything this device was holding."""
        spatial_id = session.data.get("spatial")
        self.service.release_owner(session.id)
        if spatial_id:
            with self._lock:
                self.cursors.get(spatial_id, {}).pop(session.id, None)
            self._publish_roster(spatial_id)

    def _scopes_changed(self, session: RemoteSession) -> None:
        spatial_id = session.data.get("spatial")
        if "spatial.control" not in session.scopes:
            self.service.release_owner(session.id)
        if "spatial.presence" not in session.scopes and spatial_id:
            with self._lock:
                self.cursors.get(spatial_id, {}).pop(session.id, None)
        if "spatial.view" not in session.scopes and spatial_id:
            self.hub.unsubscribe(session, channel(spatial_id))
            session.data.pop("spatial", None)
            session.outbox.push("spatial.unsubscribed", {"session_id": spatial_id, "reason": "permission removed"})
        if spatial_id:
            self._publish_roster(spatial_id)

    def _roster_changed(self, session: RemoteSession) -> None:
        if session.data.get("spatial"):
            self._publish_roster(session.data["spatial"])

    def sweep(self) -> None:
        """Expire leases eagerly and keep subscribed sessions counted as live Spatial clients."""
        self.service.sweep_leases()
        for session in self.hub.sessions.live():
            spatial_id = session.data.get("spatial")
            if spatial_id and session.state == "open":
                try:
                    self.service.session(spatial_id).touch_client()
                except (KeyError, SessionCorrupted):
                    continue

    # Kinds --------------------------------------------------------------------------
    def _register(self) -> None:
        hub = self.hub
        view, control = ("spatial.view",), ("spatial.control",)

        async def sessions(ctx: MessageContext) -> Dict[str, Any]:
            active = self.service.active_session()
            return {"sessions": self.service.sessions.list()[:50], "active": active.id if active else None}

        async def subscribe(ctx: MessageContext) -> Dict[str, Any]:
            body = ctx.envelope.body
            spatial_id = body.get("session_id")
            try:
                if spatial_id is None:
                    active = self.service.active_session()
                    if active is not None:
                        spatial_id = active.id
                    elif body.get("create") and "spatial.control" in ctx.session.scopes:
                        label = f"{ctx.session.device.get('name') or 'Remote'} Spatial Lab"
                        spatial_id = self.service.create_session(label)["session"]["id"]
                    else:
                        raise RemoteError("no_active_session", "No Spatial Lab session is open on AKASHI. Open one or create one.")
                self.service.session(str(spatial_id))
            except RemoteError:
                raise
            except Exception as exc:
                raise self._fail(exc) from exc
            previous = ctx.session.data.get("spatial")
            if previous and previous != spatial_id:
                hub.unsubscribe(ctx.session, channel(previous))
                self.service.release_owner(ctx.session.id)
                self._publish_roster(previous)
            hub.subscribe(ctx.session, channel(spatial_id))
            ctx.session.data["spatial"] = spatial_id
            self.service.session(spatial_id).touch_client()
            payload = self.sync_payload(spatial_id, body.get("revision"), body.get("digest"))
            self._publish_roster(spatial_id)
            return {"session_id": spatial_id, **payload}

        async def command(ctx: MessageContext) -> Dict[str, Any]:
            spatial_id = self._subscribed(ctx.session)
            body = ctx.envelope.body
            base = body.get("base_revision")
            if base is not None and (isinstance(base, bool) or not isinstance(base, int) or base < 0):
                raise RemoteError("bad_request", "base_revision must be a non-negative integer.")
            origin = self._origin(ctx, str(body.get("modality") or "ui"), body.get("input"))
            try:
                result = await self.service.submit(spatial_id, body.get("request"), origin, base_revision=base,
                                                   lease_owner=ctx.session.id)
            except (CommandRejected, Clarification, RequestInvalid, AssetError, FormLibraryError, KeyError, SessionCorrupted) as exc:
                raise self._fail(exc) from exc
            reply: Dict[str, Any] = {"status": result["status"], "revision": result["revision"], "targets": result["targets"],
                                     "notes": result.get("notes", [])}
            if result["status"] == "confirmation_required":
                reply.update(token=result["token"], question=result["question"])
            return reply

        async def interpret(ctx: MessageContext) -> Dict[str, Any]:
            spatial_id = self._subscribed(ctx.session)
            text = ctx.envelope.body.get("text")
            modality = str(ctx.envelope.body.get("modality") or "language")
            if not isinstance(text, str) or not 0 < len(text.strip()) <= 500:
                raise RemoteError("bad_request", "text must be 1-500 characters.")
            if modality not in {"language", "voice"}:
                raise RemoteError("bad_modality", "Instructions are 'language' or 'voice'.")
            return await self.interpret(ctx, spatial_id, text, modality)

        async def confirm(ctx: MessageContext) -> Dict[str, Any]:
            spatial_id = self._subscribed(ctx.session)
            token, accept = ctx.envelope.body.get("token"), bool(ctx.envelope.body.get("accept"))
            if not isinstance(token, str):
                raise RemoteError("bad_request", "token is required.")
            pending = self.service.pending_confirmation(spatial_id, token)
            if pending is None:
                raise RemoteError("confirmation_expired", "That confirmation expired or was already decided.")
            own = pending.get("requester") == ctx.session.id and "spatial.control" in ctx.session.scopes
            if not own and not {"approvals.spatial", "approvals.general"} & ctx.session.scopes:
                raise RemoteError("forbidden", "Only the requesting device or an approver may decide this.")
            decided_by = {"by": "requester" if own else ("owner" if ctx.session.kind == "owner" else "device"),
                          "device_id": str(ctx.session.device.get("id")), "device_name": str(ctx.session.device.get("name")),
                          "session": ctx.session.id, "at": ctx.provenance("ui")["received_at"]}
            try:
                result = await self.service.confirm(spatial_id, token, accept, decided_by=decided_by if accept else None)
            except (CommandRejected, KeyError) as exc:
                raise self._fail(exc) from exc
            return {"status": result["status"], "revision": result["revision"], "targets": result["targets"]}

        async def lease_begin(ctx: MessageContext) -> Dict[str, Any]:
            spatial_id = self._subscribed(ctx.session)
            body = ctx.envelope.body
            object_id, modality = body.get("object_id"), str(body.get("modality") or "gesture")
            if not isinstance(object_id, str) or modality not in MODALITIES:
                raise RemoteError("bad_request", "object_id and a valid modality are required.")
            base = body.get("base_revision")
            try:
                return self.service.begin_lease(spatial_id, object_id, f"remote:{modality}", owner=ctx.session.id,
                                                holder=self.holder(ctx.session, modality),
                                                base_revision=base if isinstance(base, int) and not isinstance(base, bool) else None)
            except (CommandRejected, KeyError) as exc:
                raise self._fail(exc) from exc

        async def lease_renew(ctx: MessageContext) -> Optional[Dict[str, Any]]:
            spatial_id = self._subscribed(ctx.session)
            try:
                self.service.renew_lease(spatial_id, str(ctx.envelope.body.get("lease_id")), owner=ctx.session.id)
            except (CommandRejected, KeyError) as exc:
                raise self._fail(exc) from exc
            return None

        async def lease_end(ctx: MessageContext) -> Dict[str, Any]:
            spatial_id = self._subscribed(ctx.session)
            try:
                ended = self.service.end_lease(spatial_id, str(ctx.envelope.body.get("lease_id")), owner=ctx.session.id)
            except (CommandRejected, KeyError) as exc:
                raise self._fail(exc) from exc
            return {"ended": ended}

        async def preview(ctx: MessageContext) -> Optional[Dict[str, Any]]:
            spatial_id = self._subscribed(ctx.session)
            lease_id = str(ctx.envelope.body.get("lease_id"))
            transform = valid_transform(ctx.envelope.body.get("transform"))
            owner = None if ctx.session.kind == "owner" else ctx.session.id
            session = self.service.session(spatial_id)
            try:
                with session.lock:
                    lease = session.find_lease(lease_id, owner)
            except CommandRejected as exc:
                raise self._fail(exc) from exc
            record = {"lease_id": lease_id, "object_id": lease.object_id, "transform": transform,
                      "holder": lease.holder or self.holder(ctx.session, "gesture"), "pseq": ctx.envelope.seq,
                      "sent_at_ms": ctx.envelope.t}
            with self._lock:
                self.previews.setdefault(spatial_id, {})[lease_id] = record
            hub.publish(channel(spatial_id), "spatial.preview", record, exclude=ctx.session.id, coalesce=f"preview:{lease_id}")
            return None

        async def presence(ctx: MessageContext) -> Optional[Dict[str, Any]]:
            spatial_id = self._subscribed(ctx.session)
            body = ctx.envelope.body
            anchors = body.get("anchors") or {}
            if not isinstance(anchors, dict) or set(anchors) - set(ANCHORS):
                raise RemoteError("bad_presence", "anchors may hold left_hand and right_hand only.")
            clean = {}
            for key, value in anchors.items():
                if not isinstance(value, dict) or not _finite(value.get("position"), 3):
                    raise RemoteError("bad_presence", "Each anchor needs a finite position[3].")
                confidence = value.get("confidence", 1.0)
                clean[key] = {"position": [round(float(v), 4) for v in value["position"]],
                              "confidence": max(0.0, min(1.0, float(confidence))) if isinstance(confidence, (int, float)) else 1.0}
            cursors = []
            for item in (body.get("cursors") or [])[:4]:
                if isinstance(item, dict) and _finite(item.get("position"), 3) and item.get("hand") in {"left", "right"}:
                    cursors.append({"hand": item["hand"], "position": [round(float(v), 4) for v in item["position"]],
                                    "state": item.get("state") if item.get("state") in {"open", "pinch", "grab"} else "open"})
            self.service.presence(spatial_id, clean, source=ctx.session.id)
            with self._lock:
                self.cursors.setdefault(spatial_id, {})[ctx.session.id] = {"cursors": cursors}
            hub.publish(channel(spatial_id), "spatial.presence",
                        {"session": ctx.session.id, "device": ctx.session.device_public(), "anchors": clean, "cursors": cursors},
                        exclude=ctx.session.id, coalesce=f"presence:{ctx.session.id}")
            return None

        async def provenance(ctx: MessageContext) -> Dict[str, Any]:
            spatial_id = self._subscribed(ctx.session)
            try:
                return self.service.provenance(spatial_id, str(ctx.envelope.body.get("object_id")))
            except (CommandRejected, KeyError) as exc:
                raise self._fail(exc) from exc

        async def events(ctx: MessageContext) -> Dict[str, Any]:
            spatial_id = self._subscribed(ctx.session)
            after = ctx.envelope.body.get("after", 0)
            after = after if isinstance(after, int) and not isinstance(after, bool) and after >= 0 else 0
            session = self.service.session(spatial_id)
            with session.lock:
                selected = session.history.events[after:after + MAX_EVENTS_INLINE]
                return {"revision": session.history.revision, "events": [compact_event(e) for e in selected]}

        hub.register("spatial.sessions", sessions, any_of=view)
        hub.register("spatial.subscribe", subscribe, any_of=view)
        hub.register("spatial.command", command, any_of=control)
        hub.register("spatial.interpret", interpret, any_of=control)
        hub.register("spatial.confirm", confirm, any_of=("spatial.control", "approvals.spatial", "approvals.general"),
                     rate_class="approval")
        hub.register("spatial.lease.begin", lease_begin, any_of=control)
        hub.register("spatial.lease.renew", lease_renew, delivery="realtime", any_of=control, max_age_ms=RENEW_MAX_AGE_MS)
        hub.register("spatial.lease.end", lease_end, any_of=control)
        hub.register("spatial.preview", preview, delivery="realtime", any_of=control, max_age_ms=PREVIEW_MAX_AGE_MS)
        hub.register("spatial.presence", presence, delivery="realtime", any_of=("spatial.presence",), max_age_ms=PRESENCE_MAX_AGE_MS)
        hub.register("spatial.provenance", provenance, any_of=view)
        hub.register("spatial.events", events, any_of=view)

    async def interpret(self, ctx: MessageContext, spatial_id: str, text: str, modality: str) -> Dict[str, Any]:
        try:
            outcome = await self.service.interpret(spatial_id, text, provider=f"remote:{ctx.session.device.get('device_type') or 'device'}"[:40],
                                                   voice=modality == "voice", remote=ctx.provenance(modality))
        except (CommandRejected, KeyError, SessionCorrupted) as exc:
            raise self._fail(exc) from exc
        reply = {key: outcome[key] for key in ("understood", "reply", "clarification", "confirmation", "rejected", "query",
                                                 "provenance") if key in outcome}
        reply["revision"] = self.service.session(spatial_id).history.revision
        reply["applied"] = len(outcome.get("results", []))
        if outcome.get("confirmation"):
            # The requester may confirm its own destructive request from the device.
            reply["confirmation"] = dict(outcome["confirmation"])
        return reply
