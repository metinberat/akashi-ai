"""Replaceable asynchronous Core/Agent host adapter, not generic agent internals."""

import asyncio
import hashlib
import json
import uuid
from pathlib import PureWindowsPath
from app.expertise.training.blender import TrainingBlenderAdapter, compare_saved
from .contracts import VERSION
from .geometry import construct
from .protection import protected_equivalence
from app.expertise.schema import Source
from app.expertise.store import now


class BoundaryPause(Exception):
    pass


class ProductionHost:
    def __init__(self, engine, desktop):
        self.engine, self.desktop = engine, desktop
        self.worker = None
        self.active = None
        self.stopping = False

    async def action(self, **arguments):
        result = await self.desktop.execute(
            "blender_operation", arguments, approved=True
        )
        if not result.get("ok") or not result.get("data", {}).get("verified"):
            raise RuntimeError("Production application evidence failed.")
        return result["data"]

    async def stage(self, document, path):
        payload = json.dumps(
            document, ensure_ascii=True, allow_nan=False, separators=(",", ":")
        ).encode()
        if len(payload) > 32 * 1024 * 1024:
            raise ValueError("Production staging exceeds budget.")
        sha = hashlib.sha256(payload).hexdigest()
        chunks = [
            payload[i : i + 24000].decode() for i in range(0, len(payload), 24000)
        ]
        for i, chunk in enumerate(chunks):
            result = await self.action(
                operation="stage_production",
                output=path,
                chunk=chunk,
                chunk_index=i,
                chunk_count=len(chunks),
                sha256=sha,
            )
        if not result.get("complete") or result.get("sha256") != sha:
            raise RuntimeError("Production staging incomplete.")
        return {"verified": True, "sha256": sha, "bytes": len(payload)}

    async def run(self, key):
        repo = self.engine.repository
        job = await asyncio.to_thread(repo.get, key)
        if (job.get("active_application") or {}).get("inflight"):
            raise ValueError("Ambiguous application effects require reconciliation.")
        application = job.get("active_application") or {}
        numeric_only = not application.get("done") and not application.get("inflight")
        if job["mode"] == "procedural_character" and (
            not application or (not job["best"] and numeric_only)
        ):
            job = await asyncio.to_thread(self.engine.numeric, key, 6)
            # Numeric pause can precede the first accepted candidate. Do not
            # create an application checkpoint with no document to materialize.
            if job["status"] in {"paused", "cancelled", "needs_correction"}:
                return job
        output = job["request"]["output_directory"]
        if not output:
            return job
        if not PureWindowsPath(output).is_absolute():
            raise ValueError("Output must be an absolute approved directory.")
        job, token = await asyncio.to_thread(repo.claim, key)
        if not token:
            return job
        prefix = uuid.uuid4().hex
        root = PureWindowsPath(output)
        paths = {
            k: str(root / (prefix + suffix))
            for k, suffix in (
                ("input", "-input.json"),
                ("blend", "-character.blend"),
                ("inspection", "-inspection.json"),
                ("verification", "-verification.json"),
                ("render", "-render.png"),
                ("front", "-front.png"),
                ("back", "-back.png"),
                ("flow", "-flow.png"),
                ("glb", "-character.glb"),
            )
        }
        evidence = job.get("active_application") or {
            "id": "production-app-" + prefix,
            "paths": paths,
            "status": "unverified",
            "done": [],
            "inflight": None,
            "effects_replay": "never blindly retry external effects",
        }
        paths = evidence["paths"]

        async def step(name, function):
            control = await asyncio.to_thread(repo.get, key)
            if (
                self.stopping
                or control["pause_requested"]
                or control["cancel_requested"]
            ):
                raise BoundaryPause()
            if name in evidence["done"]:
                return evidence[name]
            evidence["inflight"] = name
            await asyncio.to_thread(
                repo.save, key, token, {"status": name, "active_application": evidence}
            )
            value = await function()
            evidence[name] = value
            evidence["done"].append(name)
            evidence["inflight"] = None
            await asyncio.to_thread(
                repo.save, key, token, {"active_application": evidence}
            )
            return value

        try:
            if job["version"] != VERSION:
                raise ValueError("Production version mismatch.")
            if job["mode"] == "procedural_character":
                if not job["best"]:
                    raise ValueError("No technically accepted numeric candidate.")
                document = await asyncio.to_thread(
                    repo.document, job["best"]["document_digest"]
                )
            else:
                source = job["request"]["source_project"]
                if not source:
                    raise ValueError(
                        "Supplied asset requires its approved .blend source."
                    )
                document = construct(
                    job["request"]["design"], {"radial": 16}, job["request"]["seed"]
                )
            if "source_hash" in evidence["done"]:
                current = await self.action(
                    operation="inspect_scene", project=paths["blend"]
                )
                if current["source_sha256"] != evidence["source_hash"]["source_sha256"]:
                    raise ValueError("Saved production checkpoint changed.")
            await step("stage", lambda: self.stage(document, paths["input"]))
            if job["mode"] == "procedural_character":
                await step(
                    "build",
                    lambda: self.action(
                        operation="build_production",
                        project=paths["input"],
                        output=paths["blend"],
                        timeout_seconds=180,
                    ),
                )
            else:
                asset = self.engine.expertise.store.asset(
                    job["request"]["source_asset_id"]
                )
                expected = asset["normalized"]["metadata"].get(
                    "original_application_source_sha256"
                )
                actual = await self.action(operation="inspect_scene", project=source)
                if not expected or expected != actual["source_sha256"]:
                    raise ValueError(
                        "Source must match its ingested Blender provenance."
                    )
                await step(
                    "build",
                    lambda: self.action(
                        operation="present_production",
                        project=source,
                        patch=paths["input"],
                        output=paths["blend"],
                        timeout_seconds=180,
                    ),
                )
            await step(
                "source_hash",
                lambda: self.action(operation="inspect_scene", project=paths["blend"]),
            )
            await step(
                "inspection",
                lambda: self.action(
                    operation="inspect_character",
                    project=paths["blend"],
                    output=paths["inspection"],
                    timeout_seconds=180,
                ),
            )
            observed = await TrainingBlenderAdapter(
                self.desktop, self.engine.expertise
            ).read(paths["inspection"])
            if job["mode"] == "procedural_character":
                evidence["readback"] = compare_saved(document, observed)
                if not evidence["readback"]["verified"]:
                    raise ValueError("Saved character differs from accepted state.")
                await step(
                    "features",
                    lambda: self.action(
                        operation="verify_production",
                        project=paths["blend"],
                        output=paths["verification"],
                        timeout_seconds=240,
                    ),
                )
            else:
                original = self.engine.expertise.store.asset(
                    job["request"]["source_asset_id"]
                )["normalized"]
                evidence["protected_readback"] = protected_equivalence(
                    original, observed
                )
                evidence["source_scope"] = (
                    "presentation/copy only; supplied rig edits are separate protected workshops"
                )
            # Camera and appearance render come from the actual saved file.
            await step(
                "render",
                lambda: self.action(
                    operation="render_current",
                    project=paths["blend"],
                    output=paths["render"],
                    timeout_seconds=240,
                ),
            )
            await step(
                "export",
                lambda: self.action(
                    operation="export_gltf",
                    project=paths["blend"],
                    output=paths["glb"],
                    timeout_seconds=240,
                ),
            )
            if job["mode"] == "procedural_character":
                for name, view, frame in (
                    ("front", "Front", 1),
                    ("back", "Back", 1),
                    ("flow", "ThreeQuarter", 120),
                ):
                    # Older checkpoints may predate the additional presentation views.
                    paths.setdefault(name, str(root / (prefix + "-" + name + ".png")))
                    await step(
                        name,
                        lambda view=view, frame=frame, name=name: self.action(
                            operation="render_production",
                            project=paths["blend"],
                            output=paths[name],
                            view=view,
                            frame=frame,
                            timeout_seconds=240,
                        ),
                    )
            await step(
                "export_readback",
                lambda: self.action(
                    operation="inspect_production_export", project=paths["glb"]
                ),
            )
            if (
                job["mode"] == "procedural_character"
                and not evidence["export_readback"]["skins"]
            ):
                raise ValueError("Export lost rig/skinning.")
            evidence.update(
                status="application_verified",
                visual_fidelity="unmeasured",
                scope="technical evidence; professional completeness and reference fidelity remain partial",
            )
            if observed:
                synthetic = (
                    job["mode"] == "procedural_character"
                    or self.engine.expertise.store.asset(
                        job["request"]["source_asset_id"]
                    )["source"]["synthetic"]
                )
                observed.setdefault("metadata", {})[
                    "original_application_source_sha256"
                ] = evidence["source_hash"]["source_sha256"]
                learned = await asyncio.to_thread(
                    self.engine.expertise.ingest,
                    "production-readback.json",
                    json.dumps(observed).encode(),
                    Source(
                        reference="production:" + key,
                        synthetic=synthetic,
                        category="synthetic_fixture"
                        if synthetic
                        else "asset_observation",
                    ),
                )
                evidence["learned_asset_id"] = learned["id"]
            experience = {
                "id": "experience-" + evidence["id"],
                "task_id": evidence["id"],
                "schema_version": 3,
                "source_type": "character_production_application",
                "synthetic": job["mode"] == "procedural_character"
                or self.engine.expertise.store.asset(job["request"]["source_asset_id"])[
                    "source"
                ]["synthetic"],
                "goal": job["request"]["brief"],
                "retrieved_knowledge": job["expertise"],
                "steps": evidence["done"],
                "result": evidence,
                "verified_success": True,
                "validation_scope": "technical DCC/readback/export only; NOT artistic/reference certification",
                "artistic_success": None,
                "updated_at": now(),
            }
            return await asyncio.to_thread(
                repo.save,
                key,
                token,
                {
                    "status": "completed_partial",
                    "application": evidence,
                    "active_application": None,
                    "remaining": [
                        "reference-specific fidelity",
                        "seamless anatomical topology",
                        "production eyelids/IK/cloth",
                        "target-engine import acceptance",
                    ],
                },
                True,
                experience=experience,
            )
        except BoundaryPause:
            control = await asyncio.to_thread(repo.get, key)
            return await asyncio.to_thread(
                repo.save,
                key,
                token,
                {
                    "status": "cancelled" if control["cancel_requested"] else "paused",
                    "active_application": evidence,
                },
                True,
            )
        except Exception as exc:
            evidence.update(error_category=type(exc).__name__, status="unverified")
            await asyncio.to_thread(
                repo.save,
                key,
                token,
                {
                    "status": "paused_recovery",
                    "active_application": evidence,
                    "recovery_reason": "External effect may exist; inspect artifacts, then explicitly reconcile or create a new version.",
                },
                True,
            )
            raise

    async def reconcile(self, key):
        repo = self.engine.repository
        job, token = await asyncio.to_thread(repo.claim, key)
        if not token:
            return job
        evidence = job.get("active_application")
        try:
            if not evidence:
                raise ValueError("Owned production checkpoint required.")
            if job["mode"] == "procedural_character":
                document = await asyncio.to_thread(
                    repo.document, job["best"]["document_digest"]
                )
            else:
                asset = self.engine.expertise.store.asset(
                    job["request"]["source_asset_id"]
                )
                document = asset["normalized"]
                original = await self.action(
                    operation="inspect_scene", project=job["request"]["source_project"]
                )
                if original["source_sha256"] != document["metadata"].get(
                    "original_application_source_sha256"
                ):
                    raise ValueError("Supplied source changed; reconciliation refused.")
            paths = evidence["paths"].copy()
            root = PureWindowsPath(job["request"]["output_directory"])
            prefix = uuid.uuid4().hex
            for name, suffix in (
                ("inspection", "-inspection.json"),
                ("verification", "-verification.json"),
                ("render", "-render.png"),
                ("front", "-front.png"),
                ("back", "-back.png"),
                ("flow", "-flow.png"),
                ("glb", "-character.glb"),
            ):
                paths[name] = str(root / (prefix + suffix))
            source_hash = await self.action(
                operation="inspect_scene", project=paths["blend"]
            )
            inspection = await self.action(
                operation="inspect_character",
                project=paths["blend"],
                output=paths["inspection"],
                timeout_seconds=180,
            )
            observed = await TrainingBlenderAdapter(
                self.desktop, self.engine.expertise
            ).read(paths["inspection"])
            comparison = (
                compare_saved(document, observed)
                if job["mode"] == "procedural_character"
                else protected_equivalence(document, observed)
            )
            if not comparison["verified"]:
                raise ValueError(
                    "Ambiguous artifact does not match the accepted character."
                )
            new = {
                "id": evidence["id"],
                "paths": paths,
                "status": "unverified",
                "done": ["stage", "build", "source_hash", "inspection"],
                "inflight": None,
                "stage": {"verified": True},
                "build": {
                    "verified": True,
                    "scope": "reopened and compared, not replayed",
                },
                "source_hash": source_hash,
                "inspection": inspection,
                "previous_evidence": {
                    k: v for k, v in evidence.items() if k != "previous_evidence"
                },
                "reconciliation": "saved best-state comparison; remaining outputs use new paths",
            }
            return await asyncio.to_thread(
                repo.save,
                key,
                token,
                {"status": "paused", "active_application": new},
                True,
            )
        except Exception:
            await asyncio.to_thread(
                repo.save, key, token, {"status": "paused_recovery"}, True
            )
            raise

    async def start(self, key):
        if self.worker and not self.worker.done():
            raise ValueError("Local production already active.")
        job = await asyncio.to_thread(self.engine.repository.get, key)
        if self.worker and not self.worker.done():
            raise ValueError("Local production already active.")
        if job["status"] in {"completed_partial", "cancelled"}:
            return job
        if (job.get("active_application") or {}).get("inflight"):
            raise ValueError(
                "Ambiguous application effects require explicit inspection; no blind replay."
            )
        self.active = key

        async def work():
            try:
                await self.run(key)
            except Exception as exc:
                await asyncio.to_thread(
                    self.engine.repository.dispatch_failure, key, type(exc).__name__
                )

        self.worker = asyncio.create_task(work(), name="character-production-" + key)
        return {**job, "worker_dispatched": True}

    async def shutdown(self):
        self.stopping = True
        if self.active:
            await asyncio.to_thread(
                self.engine.repository.request, self.active, "pause"
            )
        if self.worker:
            await self.worker
