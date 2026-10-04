"""Composition of AKASHI's remote presence layer (created by the Core composition root).

hub (sessions, auth, dispatch) + Spatial Lab bridge + approvals center + remote
voice + a sweeper that applies timeouts, expires leases and pushes approval
changes. Each piece is usable on its own; this only wires them.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, Optional

from app.approvals.center import ApprovalCenter, ApprovalError, AutonomyApprovals, SpatialConfirmations, TaskApprovals
from app.devices.store import DeviceStore
from app.events.hub import EventHub
from app.remote.audit import AuditLog
from app.remote.hub import MessageContext, RemoteError, RemoteHub
from app.remote.sessions import RemoteSession, SessionConfig
from app.remote.voice import RemoteVoice
from app.spatial.remote import SpatialRemoteBridge

APPROVAL_CHANNEL = "approvals"


class RemoteRuntime:
    def __init__(self, devices: DeviceStore, *, directory: Optional[Path], spatial: Any = None, tasks: Any = None,
                 autonomy: Any = None, voice_sessions: Any = None, chat: Optional[Callable[..., Awaitable[Any]]] = None,
                 events: Optional[EventHub] = None, endpoints: Iterable[str] = (), config: SessionConfig = SessionConfig(),
                 **clock: Any) -> None:
        self.audit = AuditLog(Path(directory) / "audit" if directory is not None else None)
        self.events = events
        self.hub = RemoteHub(devices, audit=self.audit, config=config, endpoints=endpoints, **clock)
        self.spatial = SpatialRemoteBridge(spatial, self.hub) if spatial is not None else None
        self.approvals = ApprovalCenter(self.audit)
        if spatial is not None:
            self.approvals.add_source(SpatialConfirmations(spatial))
        if tasks is not None:
            self.approvals.add_source(TaskApprovals(tasks))
        if autonomy is not None:
            self.approvals.add_source(AutonomyApprovals(autonomy))
        self.voice = RemoteVoice(self.hub, self.spatial, chat, voice_sessions) if self.spatial is not None else None
        self._task: Optional[asyncio.Task] = None
        self._register_approvals()
        self.hub.on("opened", self._announce("opened"))
        self.hub.on("closed", self._announce("closed"))
        self.hub.on("stale", self._announce("stale"))
        self.hub.on("scopes", self._scopes_changed)

    def _announce(self, status: str) -> Callable[[RemoteSession], Awaitable[None]]:
        async def publish(session: RemoteSession) -> None:
            if self.events is not None:
                await self.events.publish("remote.session", {"status": status, "state": session.state,
                                                             "action": str(session.device.get("device_type"))[:40]})
            if session.state != "closed" and {"approvals.spatial", "approvals.general"} & session.scopes:
                self.hub.subscribe(session, APPROVAL_CHANNEL)
                self._push_approvals(session)
        return publish

    def _scopes_changed(self, session: RemoteSession) -> None:
        if {"approvals.spatial", "approvals.general"} & session.scopes:
            self.hub.subscribe(session, APPROVAL_CHANNEL)
            self._push_approvals(session)
        else:
            self.hub.unsubscribe(session, APPROVAL_CHANNEL)
            session.outbox.push("approvals.changed", {"approvals": []}, coalesce="approvals")

    # Approvals ----------------------------------------------------------------------
    def decided_by(self, session: RemoteSession, at: str) -> Dict[str, Any]:
        return {"by": "owner" if session.kind == "owner" else "device", "device_id": str(session.device.get("id")),
                "device_name": str(session.device.get("name")), "device_type": str(session.device.get("device_type")),
                "session": session.id, "at": at}

    def _register_approvals(self) -> None:
        approver = ("approvals.spatial", "approvals.general")

        async def list_approvals(ctx: MessageContext) -> Dict[str, Any]:
            return {"approvals": [item.public() for item in self.approvals.pending(self._scopes(ctx.session))]}

        async def decide(ctx: MessageContext) -> Dict[str, Any]:
            approval_id, approve = ctx.envelope.body.get("approval_id"), ctx.envelope.body.get("approve")
            if not isinstance(approval_id, str) or not isinstance(approve, bool):
                raise RemoteError("bad_request", "approval_id and approve (true/false) are required.")
            try:
                result = await self.approvals.decide(approval_id, approve, self.decided_by(ctx.session, ctx.provenance("ui")["received_at"]),
                                                     self._scopes(ctx.session))
            except ApprovalError as exc:
                raise RemoteError(exc.code, str(exc), status=exc.status) from exc
            self.push_approvals()
            return result

        self.hub.register("approvals.list", list_approvals, any_of=approver, rate_class="approval")
        self.hub.register("approval.decide", decide, any_of=approver, rate_class="approval")

    @staticmethod
    def _scopes(session: RemoteSession):
        return None if session.kind == "owner" else session.scopes

    def _push_approvals(self, session: RemoteSession) -> None:
        items = [item.public() for item in self.approvals.pending(self._scopes(session))]
        session.outbox.push("approvals.changed", {"approvals": items}, coalesce="approvals")

    def push_approvals(self) -> None:
        for session in self.hub.members(APPROVAL_CHANNEL):
            if session.kind == "owner" or {"approvals.spatial", "approvals.general"} & session.scopes:
                self._push_approvals(session)
            else:
                self.hub.unsubscribe(session, APPROVAL_CHANNEL)

    # Sweeper ------------------------------------------------------------------------
    async def sweep(self) -> None:
        await self.hub.sweep()
        if self.spatial is not None:
            self.spatial.sweep()
        if self.approvals.changed():
            self.push_approvals()

    async def _loop(self, interval: float) -> None:
        while True:
            try:
                await self.sweep()
            except Exception:  # keep sweeping; one failure must not stop timeouts
                self.hub.counters["sweep_error"] = self.hub.counters.get("sweep_error", 0) + 1
            await asyncio.sleep(interval)

    def start(self, interval: float = 0.5) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._loop(interval))

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
