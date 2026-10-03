"""Application/domain boundary. No AbsoluteCore, Core API, scheduler or PC runtime."""

import asyncio
import base64
import hashlib
import os
from pathlib import Path

from app.autonomy.knowledge import KnowledgeStore
from app.expertise.service import CharacterExpertiseService
from app.expertise.store import ExpertiseStore
from app.expertise.production.contracts import BuildRequest
from app.expertise.production.host import ProductionHost
from app.expertise.production.reference import ReferenceIntelligence
from app.expertise.training.blender import TrainingBlenderAdapter
from app.expertise.schema import Source
from akashi_agent.actions import ActionExecutor
from akashi_agent.config import AgentSettings

from .projects import Projects
from .partner import Partner
from .appearance_lab import AppearanceLab
from .local_shape import LocalShape
from app.expertise.production.visual import analyze, advise


class Providers:
    """Replaceable capability port, independent configuration; existing provider implementations."""

    def __init__(self):
        self.cache = {}

    def provider_for(self, capability):
        kind = os.getenv(
            "FORM_" + capability.upper() + "_PROVIDER",
            "ollama" if capability == "reasoning" else "",
        )
        model = os.getenv(
            "FORM_" + capability.upper() + "_MODEL",
            "qwen3:8b" if capability == "reasoning" else "",
        )
        if not kind or not model:
            raise ValueError("Model capability is not configured.")
        if (
            kind != "ollama"
            and os.getenv("FORM_EXTERNAL_MODELS_ENABLED", "false").lower() != "true"
        ):
            raise ValueError("Optional external model access is disabled.")
        key = kind, model
        if key not in self.cache:
            if kind == "ollama":
                from app.providers.ollama import OllamaProvider

                self.cache[key] = OllamaProvider(
                    os.getenv("FORM_OLLAMA_URL", "http://127.0.0.1:11434"), model, 65
                )
            elif kind == "gemini":
                from app.providers.gemini import GeminiProvider

                self.cache[key] = GeminiProvider(
                    os.getenv("FORM_GEMINI_API_KEY", ""), model
                )
            else:
                raise ValueError("Unsupported configured model adapter.")
        return self.cache[key]


class BlenderGateway:
    """Only the fixed DCC operation registry is exposed. No HTTP Windows Agent required."""

    def __init__(self, root):
        root = Path(root).resolve()
        self.executor = ActionExecutor(
            AgentSettings(
                token=None,
                allowed_roots=(root,),
                capture_dir=root / "unused-captures",
                credential_file=root / "unused-credential",
                action_timeout_seconds=180,
            )
        )
        self.lock = asyncio.Lock()

    async def execute(self, name, arguments, approved=False):
        if name != "blender_operation" or not approved:
            raise ValueError("Standalone engine exposes fixed Blender operations only.")
        async with self.lock:
            return await asyncio.to_thread(
                self.executor.execute, name, arguments, approved=True
            )


class Engine:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.domain = CharacterExpertiseService(
            ExpertiseStore(self.root / "expert.sqlite3"),
            KnowledgeStore(self.root / "knowledge.json"),
        )
        self.projects = Projects(self.domain.store, self.root / "projects")
        # Migrate prior output fingerprints; quarantine outlives bounded job history.
        for project in self.projects.list():
            for job in project.get("shape_jobs", []):
                evidence = job.get("evidence") or {}
                if evidence.get("output_sha256"):
                    self.projects.quarantine(
                        evidence["output_sha256"],
                        evidence.get("backend", "restricted_shape"),
                    )
        self.gateway = BlenderGateway(self.root)
        self.production = ProductionHost(self.domain.production, self.gateway)
        self.reference = ReferenceIntelligence(Providers())
        self.partner = Partner(self.reference.router)
        self.commands = asyncio.Lock()
        self.appearance = AppearanceLab(self)
        self.shape = LocalShape(self)

    def require_compute_available(self, ignore=()):
        """One product compute owner across build, resume, practice and inference."""
        for name, host in (
            ("production", self.production),
            ("visual practice", self.appearance),
            ("local shape", self.shape),
            ("rig training", self.domain.training_host),
        ):
            if name not in ignore and host.worker and not host.worker.done():
                raise ValueError(
                    f"Wait or pause active {name} before starting another compute workflow."
                )

    def recover(self):
        """Called only while the product runtime holds its exclusive process lock."""
        with self.domain.store.connection() as db:
            db.execute("DELETE FROM production_owner")
            db.execute("DELETE FROM training_compute_owner")
            import json
            from app.expertise.store import encode, now

            for table, lease, expiry in (
                ("production_jobs", "lease", "expires"),
                ("training_runs", "lease_token", "lease_until"),
            ):
                for row in db.execute(f"SELECT id,body FROM {table}").fetchall():
                    value = json.loads(row["body"])
                    if value.get(lease):
                        value.update(
                            {
                                lease: None,
                                expiry: 0,
                                "status": "paused_recovery",
                                "updated_at": now(),
                                "recovery_reason": "Product runtime restarted. Inspect saved effects before continuing.",
                            }
                        )
                        db.execute(
                            f"UPDATE {table} SET body=? WHERE id=?",
                            (encode(value), row["id"]),
                        )
        for project in self.projects.list():
            lab = project.get("visual_lab")
            if lab and lab["status"] == "running":
                lab.update(
                    status="paused_recovery",
                    reason="Runtime restarted; no visual experiment automatically resumed.",
                )
                self.projects.update(project["id"], {"visual_lab": lab})
            shapes = project.get("shape_jobs", [])
            for job in shapes:
                if job["status"] == "running":
                    job.update(
                        status="interrupted_by_restart",
                        reason="Local GPU process was interrupted. No automatic replay.",
                    )
            if shapes:
                self.projects.update(project["id"], {"shape_jobs": shapes})

    async def propose(self, key, text, use_models):
        project = self.projects.get(key)
        refs = [r for r in self.projects.files(key) if r["kind"] == "reference"]
        image = None
        if refs:
            path, _ = self.projects.resolve_file(key, refs[-1]["id"])
            mime = {".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp", ".png": "png"}[
                path.suffix
            ]
            image = (
                "data:image/"
                + mime
                + ";base64,"
                + base64.b64encode(path.read_bytes()).decode()
            )
        snapshot = self.snapshot(key)
        context = {
            "project": project,
            "recent_messages": [
                {"role": m["role"], "text": m["text"]}
                for m in self.projects.messages(key)[-12:]
            ],
            "versions": [
                {
                    "id": r["id"],
                    "status": r["status"],
                    "steps": r["steps"],
                    "technical_evaluation": r["best"]["evaluation"]
                    if r["best"]
                    else None,
                    "remaining": r["remaining"],
                }
                for r in snapshot["runs"][-3:]
            ],
            "assets": [
                {
                    "id": a["id"],
                    "name": a["name"],
                    "observed": a["analysis"]["observed"],
                    "synthetic": a["source"]["synthetic"],
                }
                for a in snapshot["assets"][-5:]
            ],
            "retrieved_expertise_data": [
                {
                    "title": k["title"],
                    "content": k["content"][:1000],
                    "metadata": k["metadata"],
                }
                for k in self.domain.knowledge.search(text[:500], 4)
            ],
        }
        reply, evidence = await self.partner.respond(context, text, image, use_models)
        if refs:
            evidence.update(
                reference_id=refs[-1]["id"],
                image_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        if reply.design:
            self.projects.update(
                key,
                {
                    "design": reply.design.model_dump(),
                    "reference_evidence": evidence,
                    "brief": text,
                },
            )
        return reply, evidence

    async def build(self, key, supplied_asset=None, visual_practice=False):
        async with self.commands:
            self.require_compute_available(
                ("visual practice",) if visual_practice else ()
            )
            if self.shape.worker and not self.shape.worker.done():
                raise ValueError(
                    "Wait for local shape inference before starting production."
                )
            if (
                not visual_practice
                and self.appearance.worker
                and not self.appearance.worker.done()
            ):
                raise ValueError(
                    "Pause visual practice before starting a separate production."
                )
            project = self.projects.get(key)
            output = self.projects.directory(key) / "outputs"
            output.mkdir(exist_ok=True)
            extra = {}
            if supplied_asset:
                self.projects.require_link(key, "asset", supplied_asset)
                # Uploaded source linkage is stored separately; raw non-Blender ingestion is inspection-only.
                paths = self.projects.links(key, "blend:" + supplied_asset)
                if not paths:
                    raise ValueError(
                        "Only ingested .blend sources support protected presentation/export. Other formats are analysis-only here."
                    )
                extra = {"source_asset_id": supplied_asset, "source_project": paths[0]}
            request = BuildRequest(
                brief=project["brief"] or project["name"],
                design=project.get("design"),
                output_directory=str(output),
                max_candidates=3,
                **extra,
            )
            if self.production.worker and not self.production.worker.done():
                raise ValueError(
                    "Production is already running. Pause or wait before creating another version."
                )
            job = self.domain.production.create(
                request, project.get("reference_evidence")
            )
            self.projects.link(key, "production", job["id"])
            await self.production.start(job["id"])
            self.projects.message(
                key,
                "engine",
                "Production started. Numeric candidates → Blender → readback → pose tests → renders → verified export.",
            )
            return job

    def snapshot(self, key):
        project = self.projects.get(key)
        runs = []
        for identifier in self.projects.links(key, "production"):
            value = self.domain.production.repository.get(identifier)
            application = (
                value.get("application") or value.get("active_application") or {}
            )
            # Register only engine-produced receipts, never arbitrary API paths.
            receipts = {
                "input": "stage",
                "blend": "source_hash",
                "inspection": "inspection",
                "verification": "features",
                "render": "render",
                "front": "front",
                "back": "back",
                "flow": "flow",
                "glb": "export_readback",
            }
            for kind, raw in application.get("paths", {}).items():
                if (
                    receipts.get(kind) in application.get("done", [])
                    and Path(raw).is_file()
                ):
                    self.projects.file(key, raw, kind, kind.upper(), identifier)
            runs.append(
                {
                    "id": identifier,
                    "status": value["status"],
                    "created_at": value["created_at"],
                    "brief": value["request"]["brief"],
                    "design": value["request"]["design"],
                    "best": value["best"],
                    "remaining": value.get("remaining", []),
                    "recovery_reason": value.get("recovery_reason"),
                    "steps": application.get("done", []),
                    "inflight": application.get("inflight"),
                    "features": application.get("features"),
                    "trials": self.domain.production.repository.trials(identifier),
                    "reference": value["reference"],
                }
            )
            runs[-1]["events"] = value.get("events", [])
        trainings = [
            self.domain.training.repository.get(k)
            for k in self.projects.links(key, "training")
        ]
        files = [
            {k: v for k, v in f.items() if k != "path"}
            for f in self.projects.files(key)
        ]
        assets = [self.domain.store.asset(k) for k in self.projects.links(key, "asset")]
        refs = [f for f in self.projects.files(key) if f["kind"] == "reference"]
        local_reference = analyze(Path(refs[-1]["path"]).read_bytes()) if refs else None
        return {
            "project": project,
            "runs": runs,
            "training": trainings,
            "files": files,
            "local_reference": local_reference,
            "capability_advisor": advise(project["brief"], local_reference),
            "local_shape": self.shape.capability(),
            "messages": self.projects.messages(key),
            "assets": [
                {
                    "id": a["id"],
                    "name": a["name"],
                    "source": a["source"],
                    "analysis": a["analysis"],
                }
                for a in assets
            ],
        }

    async def ingest(self, key, path, synthetic):
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if self.projects.quarantined(sha):
            raise ValueError(
                "Known local model output remains quarantined from expertise and training."
            )
        for project in self.projects.list():
            if any(
                j.get("evidence", {}).get("output_sha256") == sha
                for j in project.get("shape_jobs", [])
                if j.get("evidence")
            ):
                raise ValueError(
                    "Known local model output is quarantined from expertise and training ingestion due to its license."
                )
        source = Source(
            reference="form-project:" + key,
            category="synthetic_fixture" if synthetic else "asset_observation",
            synthetic=synthetic,
        )
        if path.suffix == ".blend":
            out = self.projects.directory(key)
            asset = await TrainingBlenderAdapter(
                self.gateway, self.domain
            ).ingest_blender(str(path), str(out), source)
            self.projects.link(key, "blend:" + asset["id"], str(path))
        else:
            asset = await asyncio.to_thread(
                self.domain.ingest, path.name, path.read_bytes(), source
            )
        self.projects.link(key, "asset", asset["id"])
        self.projects.message(
            key,
            "engine",
            "Asset analyzed: "
            + asset["name"]
            + ". Provenance: "
            + source.category
            + ". Missing data is not inferred as observed fact.",
        )
        return asset["id"]

    async def shutdown(self):
        await self.shape.shutdown()
        await self.appearance.shutdown()
        await self.domain.training_host.shutdown()
