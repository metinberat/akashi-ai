"""Spatial Lab application service: the one command path for every input.

INPUT (gesture | language | UI | tool | replay)
  → request validation (``requests.py``)
  → reference resolution + compilation (``compiler.py``)
  → lease / confirmation policy (this module)
  → dry-run validation of every concrete command (pure reducer)
  → ActionHistory event(s) (``app/history``) → AKASHI event hub
"""

from __future__ import annotations

import asyncio
import copy
import json
import secrets
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional

from pydantic import ValidationError

from app.events.hub import EventHub
from app.history.engine import CommandRejected, HistoryConflict, HistoryFull
from app.memory.long_term import contains_sensitive_value
from app.spatial import requests as rq
from app.spatial.assets import AssetError, AssetRegistry
from app.spatial.compiler import CompileContext, Prepared, compile_request
from app.spatial.form_library import FormLibrary, FormLibraryError
from app.spatial.glb import MAX_GLB_BYTES
from app.spatial.language import ModelInterpreter, RuleInterpreter
from app.spatial.model import LIMITS, SCENE_SCHEMA, summarize
from app.spatial.references import Clarification
from app.spatial.replies import describe, failure_reply
from app.spatial.session import PRESENCE_TTL_SECONDS, SessionCorrupted, SessionStore, SpatialSession

CONFIRMATION_TTL = 60.0
ACTIVE_CLIENT_SECONDS = 45.0
MAX_ORIGIN_INPUT = 4096


class RequestInvalid(ValueError):
    pass


class SpatialBusy(RuntimeError):
    pass


def _validation_message(exc: ValidationError) -> str:
    first = exc.errors()[0] if exc.errors() else {}
    where = ".".join(str(p) for p in first.get("loc", ()) if p not in {"function-after"})
    return f"Invalid request{(' at ' + where) if where else ''}: {first.get('msg', 'validation failed')}"[:300]


def sanitize_origin(origin: Dict[str, Any]) -> Dict[str, Any]:
    try:
        model = rq.Origin.model_validate(origin)
    except ValidationError as exc:
        raise RequestInvalid(_validation_message(exc)) from exc
    value = model.model_dump(exclude_none=True)
    payload = value.get("input")
    if payload is not None:
        text = payload.get("text")
        if isinstance(text, str) and contains_sensitive_value(text):
            payload["text"] = "[redacted: credential-like text]"
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, default=str)
        if len(encoded) > MAX_ORIGIN_INPUT:
            value["input"] = {"truncated": True, "summary": encoded[:MAX_ORIGIN_INPUT // 2]}
    return value


class SpatialLabService:
    def __init__(self, root: Path, *, form_data_dir: Optional[Path] = None, events: Optional[EventHub] = None,
                 model_provider: Optional[Callable[[], Any]] = None, interpreter: str = "auto",
                 form_library: Optional[FormLibrary] = None, monotonic: Callable[[], float] = time.monotonic,
                 max_events: int = 10_000) -> None:
        self.root = Path(root)
        self.sessions = SessionStore(self.root / "sessions", max_events=max_events, monotonic=monotonic)
        self.form = form_library or FormLibrary(form_data_dir)
        self.assets = AssetRegistry(self.root / "assets", self.form)
        self.events = events
        self.rules = RuleInterpreter()
        self.model = ModelInterpreter(model_provider) if interpreter == "auto" and model_provider else None
        self.monotonic = monotonic
        self.active_session_id: Optional[str] = None
        self.latencies: Deque[float] = deque(maxlen=500)
        self.counters: Dict[str, int] = {}

    # Capabilities -----------------------------------------------------------------
    def capabilities(self) -> Dict[str, Any]:
        return {
            "schema": SCENE_SCHEMA,
            "limits": copy.deepcopy(LIMITS),
            "request_types": rq.REQUEST_TYPES,
            "presence_ttl_seconds": PRESENCE_TTL_SECONDS,
            "max_glb_bytes": MAX_GLB_BYTES,
            "form": self.form.status(),
            "interpreters": ["rules"] + (["model"] if self.model else []),
            "scope": {
                "spatial_model": "Camera-backed 2.5D interaction: hands move objects on a plane at the object's depth. "
                                 "No depth reconstruction, occlusion, SLAM or world anchoring in V1.",
                "validation": "Physical webcam, GPU and Windows behaviour require local acceptance (docs/acceptance/spatial-lab-v1.md).",
            },
        }

    def metrics(self) -> Dict[str, Any]:
        samples = sorted(self.latencies)
        def percentile(p: float) -> Optional[float]:
            return round(samples[min(len(samples) - 1, int(p * len(samples)))], 3) if samples else None
        return {"submit_ms": {"count": len(samples), "p50": percentile(0.5), "p95": percentile(0.95), "max": samples[-1] if samples else None},
                "counters": dict(self.counters)}

    def _count(self, key: str) -> None:
        self.counters[key] = self.counters.get(key, 0) + 1

    # Sessions ---------------------------------------------------------------------
    def create_session(self, label: str = "Spatial Lab") -> Dict[str, Any]:
        session = self.sessions.create(label)
        self.active_session_id = session.id
        session.touch_client()
        return self.snapshot(session)

    def session(self, session_id: str) -> SpatialSession:
        return self.sessions.get(session_id)

    def snapshot(self, session: SpatialSession, client: bool = False) -> Dict[str, Any]:
        if client:
            session.touch_client()
            self.active_session_id = session.id
        now = self.monotonic()
        with session.lock:
            history = session.history
            pending = [{"token": token, "question": item["question"], "expires_in": round(item["expires"] - now, 1)}
                       for token, item in session.pending_confirmations.items() if item["expires"] > now]
            return {
                "session": {
                    "id": session.id,
                    "label": session.label,
                    "revision": history.revision,
                    "digest": history.digest(),
                    "can_undo": history.can_undo() and not session.active_leases(),
                    "can_redo": history.can_redo() and not session.active_leases(),
                    "leases": [lease.public(now) for lease in session.active_leases()],
                    "pending_confirmations": pending,
                    "presence_fresh": bool(session.fresh_anchors()),
                    "recovered_torn_tail": session.recovered_torn_tail,
                },
                "state": copy.deepcopy(history.state),
            }

    def active_session(self) -> Optional[SpatialSession]:
        if not self.active_session_id:
            return None
        try:
            session = self.sessions.get(self.active_session_id)
        except (KeyError, SessionCorrupted):
            return None
        seen = session.last_client_seen
        if seen is None or self.monotonic() - seen > ACTIVE_CLIENT_SECONDS:
            return None
        return session

    # Command path -----------------------------------------------------------------
    def _parse(self, request: Any):
        try:
            return rq.parse_request(request)
        except ValidationError as exc:
            raise RequestInvalid(_validation_message(exc)) from exc

    def _prepare(self, session: SpatialSession, request_model: Any) -> Prepared:
        context = CompileContext(state=session.history.state, events=session.history.events,
                                 assets=self.assets, anchors=session.fresh_anchors())
        return compile_request(request_model, context)

    def _check_leases(self, session: SpatialSession, prepared: Prepared, origin: Dict[str, Any]) -> None:
        if prepared.history and session.active_leases():
            raise CommandRejected("object_busy", "Release the object in your hand before undo or redo.")
        if prepared.lease_id:
            lease = session.find_lease(prepared.lease_id)
            if lease.object_id not in prepared.targets:
                raise CommandRejected("lease_mismatch", "The manipulation lease belongs to another object.")
        for target in prepared.targets:
            lease = session.lease_for(target)
            if lease and lease.id != prepared.lease_id:
                raise CommandRejected("object_busy", "That object is being held by a hand right now. Release it first.",
                                      {"object_id": target, "lease_origin": lease.origin})

    def _dry_run(self, session: SpatialSession, commands: List[Dict[str, Any]]) -> None:
        state = copy.deepcopy(session.history.state)
        for command in commands:
            state = session.history.domain.apply(state, copy.deepcopy(command)).state

    def _apply(self, session: SpatialSession, prepared: Prepared, origin: Dict[str, Any]) -> List[Dict[str, Any]]:
        history = session.history
        request = prepared.request
        if prepared.history == "undo":
            return [history.undo(origin, request)]
        if prepared.history == "redo":
            return [history.redo(origin, request)]
        self._dry_run(session, prepared.commands)
        produced = []
        for command in prepared.commands:
            event = history.execute(command, origin, request)
            if event is not None:
                produced.append(event)
        if prepared.lease_id:
            session.end_lease(prepared.lease_id)
        return produced

    def submit_sync(self, session_id: str, request: Any, origin: Dict[str, Any], confirmed: bool = False) -> Dict[str, Any]:
        started = time.perf_counter()
        origin = sanitize_origin(origin)
        model = self._parse(request)
        session = self.sessions.get(session_id)
        with session.lock:
            prepared = self._prepare(session, model)
            self._check_leases(session, prepared, origin)
            if prepared.risk == "confirm" and not confirmed:
                token = secrets.token_urlsafe(16)
                question = describe(model, prepared, session.history.state, "en", pending=True)
                session.pending_confirmations[token] = {
                    "prepared": prepared, "origin": origin, "revision": session.history.revision,
                    "expires": self.monotonic() + CONFIRMATION_TTL, "question": question, "request": model,
                }
                self._count("confirmation_required")
                return {"status": "confirmation_required", "token": token, "question": question,
                        "targets": prepared.targets, "revision": session.history.revision}
            produced = self._apply(session, prepared, origin)
        self.latencies.append((time.perf_counter() - started) * 1000)
        self._count("applied" if produced else "noop")
        return {"status": "applied" if produced else "noop", "events": produced, "notes": prepared.notes,
                "targets": prepared.targets, "revision": session.history.revision, "request": model}

    async def submit(self, session_id: str, request: Any, origin: Dict[str, Any], confirmed: bool = False) -> Dict[str, Any]:
        result = await asyncio.to_thread(self.submit_sync, session_id, request, origin, confirmed)
        await self._publish(session_id, result, origin)
        return result

    async def confirm(self, session_id: str, token: str, accept: bool = True) -> Dict[str, Any]:
        session = self.sessions.get(session_id)
        with session.lock:
            pending = session.pending_confirmations.pop(token, None)
            if pending is None or pending["expires"] < self.monotonic():
                raise CommandRejected("confirmation_expired", "That confirmation expired. Ask again.")
            if not accept:
                return {"status": "declined", "events": [], "notes": [], "targets": pending["prepared"].targets,
                        "revision": session.history.revision}
            if pending["revision"] != session.history.revision:
                raise CommandRejected("scene_changed", "The scene changed since the request; ask again so I can re-check the target.")
            self._check_leases(session, pending["prepared"], pending["origin"])
            produced = self._apply(session, pending["prepared"], pending["origin"])
        result = {"status": "applied" if produced else "noop", "events": produced, "notes": pending["prepared"].notes,
                  "targets": pending["prepared"].targets, "revision": session.history.revision, "request": pending["request"]}
        await self._publish(session_id, result, pending["origin"])
        return result

    async def _publish(self, session_id: str, result: Dict[str, Any], origin: Dict[str, Any]) -> None:
        if self.events is None:
            return
        for event in result.get("events", []):
            await self.events.publish("spatial.scene.changed", {
                "session_id": session_id, "revision": event["seq"], "action": event["command"]["type"],
                "status": event["kind"], "origin": origin.get("kind", "unknown"),
            })

    # Interactions -----------------------------------------------------------------
    def begin_lease(self, session_id: str, object_id: str, origin: str) -> Dict[str, Any]:
        session = self.sessions.get(session_id)
        with session.lock:
            lease = session.begin_lease(object_id, origin)
            return lease.public(self.monotonic())

    def renew_lease(self, session_id: str, lease_id: str) -> Dict[str, Any]:
        session = self.sessions.get(session_id)
        with session.lock:
            return session.renew_lease(lease_id).public(self.monotonic())

    def end_lease(self, session_id: str, lease_id: str) -> bool:
        session = self.sessions.get(session_id)
        with session.lock:
            return session.end_lease(lease_id)

    def presence(self, session_id: str, anchors: Dict[str, Any]) -> None:
        session = self.sessions.get(session_id)
        with session.lock:
            session.set_presence(anchors)
        self.active_session_id = session.id

    # Language ---------------------------------------------------------------------
    async def interpret(self, session_id: str, text: str, *, provider: str = "ui:command-bar",
                        execute: bool = True, voice: bool = False) -> Dict[str, Any]:
        session = self.sessions.get(session_id)
        summary = summarize(session.history.state)
        interpretation = self.rules.interpret(text, summary)
        if interpretation is None and self.model is not None:
            interpretation = await self.model.interpret(text, summary)
        language = interpretation.language if interpretation else ("tr" if any(c in text for c in "çğıöşüÇĞİÖŞÜ") else "en")
        if interpretation is None:
            self._count("not_understood")
            return {"understood": False, "reply": failure_reply("not_understood", language), "results": []}
        origin = {"kind": "language", "provider": f"{provider}+{interpretation.source}",
                  "input": {"text": text[:500], "rule": interpretation.rule, "voice": voice}}
        outcome: Dict[str, Any] = {"understood": True, "interpretation": {
            "source": interpretation.source, "rule": interpretation.rule, "language": language,
            "requests": interpretation.requests}, "results": []}
        if not execute:
            outcome["reply"] = "Interpretation only; nothing was changed."
            return outcome
        replies = []
        for request in interpretation.requests:
            try:
                result = await self.submit(session_id, request, origin)
            except Clarification as exc:
                outcome.update(clarification={"code": exc.code, "question": exc.question, "candidates": exc.candidates})
                replies.append(failure_reply(exc.code, language, exc.question))
                break
            except (CommandRejected, RequestInvalid, AssetError, FormLibraryError) as exc:
                code = getattr(exc, "code", "rejected")
                outcome.update(rejected={"code": code, "message": str(exc)})
                replies.append(failure_reply(code, language, str(exc)))
                break
            if result["status"] == "confirmation_required":
                outcome["confirmation"] = {"token": result["token"], "question": result["question"]}
                replies.append(failure_reply("confirmation_required", language, result["question"]))
                break
            state = session.history.state
            outcome["results"].append({k: v for k, v in result.items() if k != "request"})
            replies.append(describe(result["request"], result, state, language))
        outcome["reply"] = " ".join(r for r in replies if r)
        return outcome

    # History ----------------------------------------------------------------------
    def events_page(self, session_id: str, after: int = 0, limit: int = 200) -> Dict[str, Any]:
        session = self.sessions.get(session_id)
        with session.lock:
            events = session.history.events[after:after + max(1, min(limit, 500))]
            return {"session_id": session_id, "revision": session.history.revision,
                    "initial_state": copy.deepcopy(session.history.initial_state) if after == 0 else None,
                    "events": copy.deepcopy(events)}

    def verify_replay(self, session_id: str) -> Dict[str, Any]:
        session = self.sessions.get(session_id)
        with session.lock:
            report = session.history.verify_replay()
            return {"verified": report.verified, "events": report.events, "commands": report.commands,
                    "undos": report.undos, "redos": report.redos, "final_digest": report.final_digest,
                    "live_digest": session.history.digest(), "matches_live_state": report.final_digest == session.history.digest()}

    def state_at(self, session_id: str, seq: int) -> Dict[str, Any]:
        session = self.sessions.get(session_id)
        with session.lock:
            return {"seq": seq, "state": session.history.state_at(seq)}


__all__ = ["SpatialLabService", "RequestInvalid", "SpatialBusy", "Clarification", "CommandRejected",
           "HistoryConflict", "HistoryFull", "SessionCorrupted"]
