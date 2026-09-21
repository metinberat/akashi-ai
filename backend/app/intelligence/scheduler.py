"""Small durable scheduler for Miss Minutes jobs."""

import asyncio
import json
import os
import re
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Awaitable, BinaryIO, Callable, Dict, List, Optional, cast


JobHandler = Callable[[], Awaitable[Dict[str, Any]]]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProcessFileLease:
    """Hold a non-blocking OS file lock for one scheduler owner."""

    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self._handle: Optional[BinaryIO] = None

    def acquire(self) -> bool:
        if self._handle is not None:
            return True
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.file_path.open("a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError):
            handle.close()
            return False
        handle.seek(0)
        marker = json.dumps({"pid": os.getpid(), "acquired_at": utc_now().isoformat()})
        handle.write(marker.encode("utf-8"))
        handle.flush()
        self._handle = handle
        return True

    def release(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


class JSONScheduleStore:
    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self._lock = Lock()
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self._write({"version": 1, "jobs": []})

    def _read(self) -> Dict[str, Any]:
        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("jobs", []), list):
                raise ValueError("Invalid schedule document")
            return cast(Dict[str, Any], data)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Schedule store at '{self.file_path}' is unreadable; it was not overwritten.") from exc

    def _write(self, data: Dict[str, Any]) -> None:
        temporary = self.file_path.with_suffix(f"{self.file_path.suffix}.tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.file_path)

    def recover_interrupted(self) -> None:
        with self._lock:
            data = self._read()
            changed = False
            for job in data["jobs"]:
                if job.get("status") == "running":
                    job["status"] = "failed"
                    job["last_error"] = "Backend restarted while this job was running."
                    job["lease"] = None
                    changed = True
            if changed:
                self._write(data)

    def ensure_interval(
        self,
        job_id: str,
        name: str,
        kind: str,
        interval_minutes: int,
        timezone_name: str,
        enabled: bool,
        missed_policy: str = "run_once",
    ) -> Dict[str, Any]:
        if missed_policy not in {"run_once", "skip"}:
            raise ValueError("Unsupported missed-job policy.")
        if timezone_name != "UTC" and not re.fullmatch(r"[A-Za-z]+(?:/[A-Za-z0-9_+\-]+)+", timezone_name):
            raise ValueError("Scheduler time zone must be UTC or an IANA-style name.")
        with self._lock:
            data = self._read()
            existing = next((item for item in data["jobs"] if item.get("id") == job_id), None)
            if existing:
                return deepcopy(existing)
            now = utc_now()
            job = {
                "id": job_id,
                "name": name,
                "kind": kind,
                "interval_minutes": max(5, min(int(interval_minutes), 43_200)),
                "timezone": timezone_name,
                "missed_policy": missed_policy,
                "enabled": bool(enabled),
                "status": "scheduled" if enabled else "disabled",
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "last_run_at": None,
                "next_run_at": (now + timedelta(minutes=interval_minutes)).isoformat(),
                "last_error": None,
                "lease": None,
                "history": [],
            }
            data["jobs"].append(job)
            self._write(data)
            return deepcopy(job)

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return deepcopy(self._read()["jobs"])

    def set_enabled(self, job_id: str, enabled: bool) -> Dict[str, Any]:
        with self._lock:
            data = self._read()
            job = next((item for item in data["jobs"] if item.get("id") == job_id), None)
            if job is None:
                raise KeyError("Schedule was not found.")
            job["enabled"] = bool(enabled)
            job["status"] = "scheduled" if enabled else "disabled"
            job["next_run_at"] = (utc_now() + timedelta(minutes=job["interval_minutes"])).isoformat()
            job["updated_at"] = utc_now().isoformat()
            self._write(data)
            return deepcopy(job)

    def claim(self, job_id: str, force: bool = False) -> Optional[Dict[str, Any]]:
        with self._lock:
            data = self._read()
            job = next((item for item in data["jobs"] if item.get("id") == job_id), None)
            if job is None or job.get("status") == "running":
                return None
            now = utc_now()
            if not force:
                if not job.get("enabled") or datetime.fromisoformat(job["next_run_at"]) > now:
                    return None
                if job.get("missed_policy") == "skip" and now - datetime.fromisoformat(job["next_run_at"]) > timedelta(minutes=job["interval_minutes"]):
                    job["next_run_at"] = (now + timedelta(minutes=job["interval_minutes"])).isoformat()
                    job["updated_at"] = now.isoformat()
                    self._write(data)
                    return None
            lease = str(uuid.uuid4())
            job["status"] = "running"
            job["lease"] = lease
            job["updated_at"] = now.isoformat()
            self._write(data)
            output = deepcopy(job)
            output["lease"] = lease
            return output

    def complete(self, job_id: str, lease: str, result: Optional[Dict[str, Any]], error: Optional[str]) -> Dict[str, Any]:
        with self._lock:
            data = self._read()
            job = next((item for item in data["jobs"] if item.get("id") == job_id), None)
            if job is None or job.get("lease") != lease:
                raise RuntimeError("Scheduler lease no longer owns this job.")
            now = utc_now()
            job["last_run_at"] = now.isoformat()
            job["next_run_at"] = (now + timedelta(minutes=job["interval_minutes"])).isoformat()
            job["status"] = "scheduled" if job.get("enabled") else "disabled"
            job["last_error"] = error[:1_000] if error else None
            job["lease"] = None
            job["updated_at"] = now.isoformat()
            job.setdefault("history", []).append({
                "timestamp": now.isoformat(),
                "status": "failed" if error else "completed",
                "result": result,
                "error": error[:1_000] if error else None,
            })
            job["history"] = job["history"][-30:]
            self._write(data)
            return deepcopy(job)


class DurableScheduler:
    def __init__(self, store: JSONScheduleStore, poll_seconds: float = 30.0) -> None:
        self.store = store
        self.poll_seconds = max(5.0, poll_seconds)
        self.handlers: Dict[str, JobHandler] = {}
        self._loop_task: Optional[asyncio.Task[None]] = None
        self._running: Dict[str, asyncio.Task[Dict[str, Any]]] = {}
        self._owner_lease = ProcessFileLease(
            store.file_path.with_suffix(f"{store.file_path.suffix}.owner.lock")
        )
        self._startup_attempted = False
        self.is_owner = False

    def register(self, kind: str, handler: JobHandler) -> None:
        self.handlers[kind] = handler

    def start(self) -> bool:
        self._startup_attempted = True
        if self.is_owner and self._loop_task is not None and not self._loop_task.done():
            return True
        if not self.is_owner:
            self.is_owner = self._owner_lease.acquire()
        if not self.is_owner:
            return False
        self.store.recover_interrupted()
        if self._loop_task is None or self._loop_task.done():
            self._loop_task = asyncio.create_task(self._loop())
        return True

    async def stop(self) -> None:
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            await asyncio.gather(self._loop_task, return_exceptions=True)
        for task in tuple(self._running.values()):
            task.cancel()
        if self._running:
            await asyncio.gather(*self._running.values(), return_exceptions=True)
        self._running.clear()
        self._owner_lease.release()
        self.is_owner = False

    async def _loop(self) -> None:
        while True:
            await self.run_due_once()
            await asyncio.sleep(self.poll_seconds)

    async def run_due_once(self) -> None:
        for job in self.store.list():
            if job["id"] in self._running:
                continue
            claimed = self.store.claim(job["id"])
            if claimed is not None:
                task = asyncio.create_task(self._execute(claimed))
                self._running[job["id"]] = task
                task.add_done_callback(lambda _task, job_id=job["id"]: self._running.pop(job_id, None))

    async def run_now(self, job_id: str) -> Dict[str, Any]:
        if self._startup_attempted and not self.is_owner:
            raise RuntimeError("This Core process does not own the scheduler lease.")
        if job_id in self._running:
            raise RuntimeError("Schedule is already running.")
        claimed = self.store.claim(job_id, force=True)
        if claimed is None:
            raise RuntimeError("Schedule could not be claimed.")
        return await self._execute(claimed)

    async def _execute(self, job: Dict[str, Any]) -> Dict[str, Any]:
        handler = self.handlers.get(job["kind"])
        if handler is None:
            return self.store.complete(job["id"], job["lease"], None, "No handler is registered for this job kind.")
        try:
            result = await handler()
        except asyncio.CancelledError:
            self.store.complete(job["id"], job["lease"], None, "Scheduler stopped during execution.")
            raise
        except Exception as exc:
            return self.store.complete(job["id"], job["lease"], None, f"{type(exc).__name__}: {exc}")
        return self.store.complete(job["id"], job["lease"], result, None)
