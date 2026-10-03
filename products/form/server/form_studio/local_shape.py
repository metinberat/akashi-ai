"""Operator-configured optional local shape channel. No network/downloads/Core.

Vendor outputs remain a separate quarantine lineage: no auto-ingestion, recipes,
RAG, self-training or dataset export. Existing 57-joint production is unaffected.
"""

import asyncio
import hashlib
import json
import os
import sys
import subprocess
import threading
import uuid
from pathlib import Path

from app.expertise.store import now


class LocalShape:
    def __init__(self, engine):
        self.engine = engine
        self.worker = None
        self.process = None
        self.key = None

    def settings(self):
        fields = {
            name: os.getenv("FORM_SHAPE_" + name.upper(), "")
            for name in ("python", "sdk", "checkpoint", "config")
        }
        for key, raw in fields.items():
            if not raw or not Path(raw).is_absolute():
                raise ValueError(
                    "Local shape runtime paths must be configured by the operator."
                )
            path = Path(raw).resolve()
            if (key == "sdk" and not path.is_dir()) or (
                key != "sdk" and not path.is_file()
            ):
                raise ValueError("Local shape runtime/model is unavailable.")
            fields[key] = str(path)
        if (
            Path(fields["python"]).name.lower() != "python.exe"
            or Path(fields["checkpoint"]).suffix != ".safetensors"
        ):
            raise ValueError("Fixed Python and safetensors are required.")
        if (
            os.getenv("FORM_LOCAL_SHAPE_ENABLED", "false").lower() != "true"
            or os.getenv("FORM_SHAPE_LICENSE_ACCEPTED", "false").lower() != "true"
        ):
            raise ValueError(
                "Experimental shape adapter is disabled pending explicit license/configuration acceptance."
            )
        return fields

    def capability(self):
        try:
            self.settings()
            ready = True
        except ValueError:
            ready = False
        return {
            "configured": ready,
            "busy": bool(self.worker and not self.worker.done()),
            "external_api_required": False,
            "scope": "experimental local shape proposal, no rig/texture generation",
            "training_allowed": False,
        }

    async def start(self, key, reference_id, quality="draft"):
        async with self.engine.commands:
            config = self.settings()
            self.engine.require_compute_available()
            if self.worker and not self.worker.done():
                raise ValueError("Local shape inference is already running.")
            if (
                self.engine.production.worker
                and not self.engine.production.worker.done()
                or self.engine.appearance.worker
                and not self.engine.appearance.worker.done()
            ):
                raise ValueError(
                    "Wait or pause production before a GPU shape experiment."
                )
            source, record = self.engine.projects.resolve_file(key, reference_id)
            if record["kind"] != "reference" or quality not in {"draft", "quality"}:
                raise ValueError(
                    "An uploaded reference and supported quality are required."
                )
            identifier = uuid.uuid4().hex
            root = self.engine.projects.directory(key)
            paths = {
                "output": root / (identifier + "-shape.glb"),
                "receipt": root / (identifier + "-shape.json"),
            }
            job = {
                "id": identifier,
                "status": "running",
                "reference_id": reference_id,
                "created_at": now(),
                "quality": quality,
                "training_allowed": False,
                "output": None,
                "evidence": None,
            }
            jobs = self.engine.projects.get(key).get("shape_jobs", [])
            self.engine.projects.update(key, {"shape_jobs": (jobs + [job])[-30:]})
            self.key = key
            self.worker = asyncio.create_task(self.run(key, job, source, paths, config))
            return job

    def save(self, key, job):
        jobs = self.engine.projects.get(key).get("shape_jobs", [])
        self.engine.projects.update(
            key, {"shape_jobs": [job if j["id"] == job["id"] else j for j in jobs]}
        )

    async def run(self, key, job, source, paths, config):
        try:
            env = {
                k: os.environ[k]
                for k in (
                    "SystemRoot",
                    "WINDIR",
                    "PATH",
                    "TEMP",
                    "TMP",
                    "USERPROFILE",
                    "LOCALAPPDATA",
                )
                if k in os.environ
            }
            env.update(
                PYTHONPATH=config["sdk"],
                HF_HUB_OFFLINE="1",
                TRANSFORMERS_OFFLINE="1",
                HF_HUB_DISABLE_TELEMETRY="1",
                PYTHONUNBUFFERED="1",
            )
            command = [
                config["python"],
                str(Path(__file__).with_name("shape_worker.py")),
                "--reference",
                str(source),
                "--checkpoint",
                config["checkpoint"],
                "--config",
                config["config"],
                "--output",
                str(paths["output"]),
                "--receipt",
                str(paths["receipt"]),
                "--steps",
                "30" if job["quality"] == "quality" else "12",
                "--resolution",
                "256" if job["quality"] == "quality" else "192",
            ]
            kwargs = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
            self.process = subprocess.Popen(
                command,
                cwd=config["sdk"],
                env=env,
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **kwargs,
            )

            # Drain logs incrementally without persisting vendor diagnostics/private paths.
            def drain(stream):
                while stream.read(4096):
                    pass
                stream.close()

            drains = [
                threading.Thread(target=drain, args=(s,), daemon=True)
                for s in (self.process.stdout, self.process.stderr)
            ]
            for thread in drains:
                thread.start()
            try:
                await asyncio.to_thread(self.process.wait, timeout=600)
            finally:
                if self.process.poll() is None:
                    self.process.kill()
                    await asyncio.to_thread(self.process.wait, timeout=10)
                for thread in drains:
                    await asyncio.to_thread(thread.join, timeout=10)
            if self.process.returncode != 0 or not paths["receipt"].is_file():
                if paths["receipt"].is_file():
                    failure = json.loads(paths["receipt"].read_text(encoding="utf-8"))
                    if failure.get("error_category") == "ReferenceForegroundError":
                        job["reason"] = (
                            "Foreground estimate was partial/ambiguous. Supply a clean character crop or alpha mask; no shape accepted."
                        )
                raise RuntimeError("Local shape inference did not verify output.")
            evidence = json.loads(paths["receipt"].read_text(encoding="utf-8"))
            if (
                not evidence.get("verified")
                or not paths["output"].is_file()
                or paths["output"].stat().st_size > 128 * 1024 * 1024
            ):
                raise ValueError("Shape export is unavailable or outside budget.")
            fingerprint = hashlib.sha256(paths["output"].read_bytes()).hexdigest()
            if fingerprint != evidence.get("output_sha256"):
                raise ValueError(
                    "Shape artifact fingerprint does not match its receipt."
                )
            self.engine.projects.quarantine(fingerprint, evidence["backend"])
            file = self.engine.projects.file(
                key,
                paths["output"],
                "shape",
                "LOCAL SHAPE / NO RIG / TRAINING RESTRICTED",
                job["id"],
            )
            job.update(
                status="completed_partial",
                evidence=evidence,
                output=file["id"],
                ended_at=now(),
            )
            prepared = paths["output"].with_name(
                paths["output"].stem + "-reference.png"
            )
            if prepared.is_file():
                preview = self.engine.projects.file(
                    key,
                    prepared,
                    "shape_reference",
                    "LOCAL FOREGROUND ESTIMATE",
                    job["id"],
                )
                job["reference_preview"] = preview["id"]
        except Exception as exc:
            job.update(
                status="failed",
                error_category=type(exc).__name__,
                ended_at=now(),
                reason=job.get("reason")
                or "No verified shape export. Existing character versions are preserved.",
            )
        finally:
            self.process = None
            self.save(key, job)

    async def shutdown(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
        if self.worker and not self.worker.done():
            await self.worker
