"""One view over every pending AKASHI approval, decidable from any authorized surface.

The center owns no approval state. Each source keeps its own (Spatial Lab
confirmations, task-engine approvals, autonomy approvals) and the center reads
them through small adapters, so there is no second registry to drift. Decisions
are routed back to the owning subsystem and recorded in the hash-chained remote
audit trail together with who decided and from which device/session.

Scope: Spatial Lab confirmations are ``spatial``; task and autonomy approvals
are ``general``. A remote device needs ``approvals.spatial`` for the first and
``approvals.general`` for both. Connecting a Spatial client therefore never
grants approval of general computer actions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Protocol

from app.remote.audit import AuditLog

SPATIAL_SCOPES = frozenset({"approvals.spatial", "approvals.general"})
GENERAL_SCOPES = frozenset({"approvals.general"})


class ApprovalError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass
class ApprovalItem:
    id: str
    source: str
    scope: str  # "spatial" | "general"
    title: str
    reason: str
    action: str
    risk: str
    requested_by: Dict[str, Any] = field(default_factory=dict)
    expires_in: Optional[float] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def public(self) -> Dict[str, Any]:
        return {"id": self.id, "source": self.source, "scope": self.scope, "title": self.title[:300], "reason": self.reason[:500],
                "action": self.action[:200], "risk": self.risk, "requested_by": self.requested_by, "expires_in": self.expires_in,
                "details": self.details}


class ApprovalSource(Protocol):
    name: str

    def pending(self) -> List[ApprovalItem]: ...

    async def decide(self, local_id: str, approve: bool, by: Dict[str, Any]) -> Dict[str, Any]: ...


def allowed(item_scope: str, session_scopes: Optional[FrozenSet[str]]) -> bool:
    """``None`` means the owner (API token), who may decide everything."""
    if session_scopes is None:
        return True
    return bool((SPATIAL_SCOPES if item_scope == "spatial" else GENERAL_SCOPES) & session_scopes)


class ApprovalCenter:
    def __init__(self, audit: AuditLog) -> None:
        self.audit = audit
        self.sources: Dict[str, ApprovalSource] = {}
        self._signature = ""
        self.listeners: List[Any] = []

    def add_source(self, source: ApprovalSource) -> None:
        self.sources[source.name] = source

    def pending(self, scopes: Optional[FrozenSet[str]] = None) -> List[ApprovalItem]:
        items: List[ApprovalItem] = []
        for source in self.sources.values():
            try:
                items.extend(source.pending())
            except Exception:  # a broken source must not hide the others
                continue
        return [item for item in items if allowed(item.scope, scopes)]

    def get(self, approval_id: str) -> Optional[ApprovalItem]:
        return next((item for item in self.pending() if item.id == approval_id), None)

    async def decide(self, approval_id: str, approve: bool, by: Dict[str, Any], scopes: Optional[FrozenSet[str]] = None) -> Dict[str, Any]:
        self.audit.require()
        source_name, _, local_id = approval_id.partition(":")
        source = self.sources.get(source_name)
        item = self.get(approval_id) if source else None
        if item is None:
            prior = self._prior_decision(approval_id)
            if prior is not None:
                return {"status": "already_decided", "decision": prior}
            raise ApprovalError("approval_not_pending", "That approval is no longer pending.", 404)
        if not allowed(item.scope, scopes):
            self.audit.record_limited(f"approval-forbidden:{by.get('session')}", 30.0, "approval.forbidden",
                                      approval_id=approval_id, scope=item.scope, by=by)
            raise ApprovalError("forbidden", "This device may not decide that approval.", 403)
        try:
            outcome = await source.decide(local_id, approve, by)
        except ApprovalError:
            raise
        except Exception as exc:
            self.audit.record("approval.failed", approval_id=approval_id, source=item.source, scope=item.scope,
                              decision="approve" if approve else "deny", by=by, error=str(exc)[:300])
            raise ApprovalError(getattr(exc, "code", "approval_failed"), str(exc)[:300], 409) from exc
        record = self.audit.record("approval.decided", approval_id=approval_id, source=item.source, scope=item.scope,
                                   title=item.title[:300], action=item.action[:200], decision="approve" if approve else "deny",
                                   by=by, outcome={k: v for k, v in outcome.items() if isinstance(v, (str, int, bool))})
        return {"status": "decided", "decision": "approve" if approve else "deny", "outcome": outcome, "audit_seq": record["seq"]}

    def _prior_decision(self, approval_id: str) -> Optional[Dict[str, Any]]:
        if self.audit.log is None:
            return None
        for event in reversed(self.audit.log.events[-2000:]):
            if event.get("kind") == "approval.decided" and event.get("approval_id") == approval_id:
                return {"decision": event.get("decision"), "by": event.get("by"), "at": event.get("at"), "audit_seq": event["seq"]}
        return None

    def changed(self) -> bool:
        """True when the pending set changed since the last call (cheap polling of the sources)."""
        signature = hashlib.sha256(json.dumps(sorted(item.id for item in self.pending())).encode()).hexdigest()
        if signature == self._signature:
            return False
        self._signature = signature
        return True


class SpatialConfirmations:
    name = "spatial"

    def __init__(self, service: Any) -> None:
        self.service = service

    def pending(self) -> List[ApprovalItem]:
        items = []
        for entry in self.service.pending_confirmations():
            items.append(ApprovalItem(
                id=f"spatial:{entry['session_id']}:{entry['token']}", source="spatial", scope="spatial",
                title=entry["question"], action=entry["request"].get("type", "scene"), risk="confirm",
                reason="Spatial Lab asks before removing anything from the shared scene.",
                requested_by=entry["requested_by"], expires_in=entry["expires_in"],
                details={"session_id": entry["session_id"], "session_label": entry["session_label"], "targets": entry["targets"]}))
        return items

    async def decide(self, local_id: str, approve: bool, by: Dict[str, Any]) -> Dict[str, Any]:
        session_id, _, token = local_id.partition(":")
        decided_by = {"by": by.get("by", "device"), "device_id": by.get("device_id"), "device_name": by.get("device_name"),
                      "session": by.get("session"), "at": by.get("at")}
        result = await self.service.confirm(session_id, token, approve, decided_by=decided_by if approve else None)
        return {"status": result["status"], "revision": result["revision"]}


class TaskApprovals:
    name = "task"

    def __init__(self, engine: Any) -> None:
        self.engine = engine

    def pending(self) -> List[ApprovalItem]:
        items = []
        for task in self.engine.store.list(200):
            if task.get("status") != "waiting_for_approval":
                continue
            risky = [step.get("tool", "?") for step in task.get("steps", []) if step.get("risk") == "confirm"]
            items.append(ApprovalItem(
                id=f"task:{task['id']}", source="task", scope="general", title=f"Run task: {task.get('title', '')}",
                action=", ".join(risky) or "task", risk="confirm",
                reason=f"These tools act outside the conversation and need explicit approval: {', '.join(risky) or 'n/a'}.",
                requested_by={"en": "AKASHI task engine", "tr": "AKASHI görev motoru"},
                details={"task_id": task["id"], "steps": len(task.get("steps", [])), "created_at": task.get("created_at")}))
        return items

    async def decide(self, local_id: str, approve: bool, by: Dict[str, Any]) -> Dict[str, Any]:
        task = await (self.engine.approve(local_id) if approve else self.engine.cancel(local_id))
        return {"status": task.get("status", "unknown")}


class AutonomyApprovals:
    name = "autonomy"

    def __init__(self, engine: Any) -> None:
        self.engine = engine

    def pending(self) -> List[ApprovalItem]:
        items = []
        for task in self.engine.store.list(200):
            if task.get("status") != "waiting_for_approval":
                continue
            reason = next((e.get("summary", "") for e in reversed(task.get("events", [])) if e.get("kind") == "approval"), "")
            items.append(ApprovalItem(
                id=f"autonomy:{task['id']}", source="autonomy", scope="general", title=f"Continue: {task.get('goal', '')}"[:300],
                action="autonomy step", risk="confirm", reason=reason or "The next step acts on this computer and needs approval.",
                requested_by={"en": "AKASHI autonomy", "tr": "AKASHI otonomi"},
                details={"task_id": task["id"], "updated_at": task.get("updated_at")}))
        return items

    async def decide(self, local_id: str, approve: bool, by: Dict[str, Any]) -> Dict[str, Any]:
        task = await (self.engine.resume(local_id, approved=True) if approve else self.engine.cancel(local_id))
        return {"status": task.get("status", "unknown")}
