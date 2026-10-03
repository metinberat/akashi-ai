import asyncio
import hashlib
import json
import secrets
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from app.expertise.production.contracts import Design
from app.expertise.training.contracts import TrainingRequest
from app.memory.long_term import contains_sensitive_value
from .engine import Engine
from .limits import BodyLimit


class ProjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    brief: str = Field(default="", max_length=3500)


class MessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=3500)
    use_models: bool = True


class BuildInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str | None = None


class BestInput(BaseModel):
    run_id: str


class VisualInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference_id: str = Field(max_length=128)
    attempts: int = Field(default=2, ge=1, le=3, strict=True)


class AssessmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference_id: str = Field(max_length=128)
    run_id: str = Field(max_length=128)


class ShapeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference_id: str = Field(max_length=128)
    quality: Literal["draft", "quality"] = "draft"


def clean(text):
    if contains_sensitive_value(text):
        raise ValueError("Credential-like text must not enter project memory.")
    return text.strip()


def create_app(root, token, web, shutdown_callback=None, recover=False):
    if len(token) < 32:
        raise ValueError("A strong local application token is required.")
    engine = Engine(root)

    @asynccontextmanager
    async def lifespan(app):
        if recover:
            engine.recover()
        yield
        await engine.shutdown()

    app = FastAPI(
        title="FORM Character Studio",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.engine = engine
    app.add_middleware(BodyLimit)

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        host = request.headers.get("host", "").split(":")[0]
        if host not in {"127.0.0.1", "localhost", "testserver"}:
            return JSONResponse({"detail": "Local host only."}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse(
                {"detail": "Cross-origin requests are forbidden."}, status_code=403
            )
        if request.url.path.startswith("/api/"):
            provided = request.headers.get("authorization", "")
            if not secrets.compare_digest(provided, "Bearer " + token):
                return JSONResponse(
                    {"detail": "Application authentication required."}, status_code=401
                )
            try:
                content_length = int(request.headers.get("content-length", "0"))
            except ValueError:
                return JSONResponse(
                    {"detail": "Invalid request length."}, status_code=400
                )
            if content_length > 130 * 1024 * 1024:
                return JSONResponse(
                    {"detail": "Request exceeds budget."}, status_code=413
                )
        try:
            response = await call_next(request)
        except (UnidentifiedImageError, Image.DecompressionBombError):
            return JSONResponse(
                {"detail": "Invalid image or excessive pixel count."}, status_code=422
            )
        except (OSError, RuntimeError):
            return JSONResponse(
                {
                    "detail": "Local engine operation failed. Saved project state is retained; inspect the version evidence."
                },
                status_code=503,
            )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; connect-src 'self' blob:; worker-src 'self' blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    @app.exception_handler(KeyError)
    async def missing(_request, _exc):
        return JSONResponse({"detail": "Project or result not found."}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(_request, exc):
        # Validation messages from fixed domain operations only, never credentials or model output.
        return JSONResponse({"detail": str(exc)[:500]}, status_code=409)

    @app.get("/api/health")
    async def health():
        return {
            "product": "FORM",
            "core_required": False,
            "blender": bool(engine.gateway.executor.apps.get("blender")),
            "production_busy": bool(
                engine.production.worker and not engine.production.worker.done()
            ),
            "scope": "Synthetic stylized humanoid production; artistic fidelity is unmeasured.",
        }

    @app.get("/api/projects")
    async def projects():
        return engine.projects.list()

    @app.post("/api/projects", status_code=201)
    async def create(value: ProjectInput):
        if not value.name.strip():
            raise ValueError("Project name is required.")
        return engine.projects.create(clean(value.name), clean(value.brief))

    @app.get("/api/projects/{key}")
    async def inspect(key: str):
        return await asyncio.to_thread(engine.snapshot, key)

    @app.put("/api/projects/{key}/brief")
    async def brief(key: str, value: ProjectInput):
        return engine.projects.update(
            key, {"name": clean(value.name), "brief": clean(value.brief)}
        )

    @app.put("/api/projects/{key}/design")
    async def design(key: str, value: Design):
        return engine.projects.update(key, {"design": value.model_dump()})

    @app.post("/api/projects/{key}/messages")
    async def message(key: str, value: MessageInput):
        text = clean(value.text)
        engine.projects.message(key, "user", text)
        reply, evidence = await engine.propose(key, text, value.use_models)
        return engine.projects.message(key, "assistant", clean(reply.text), evidence)

    @app.post("/api/projects/{key}/uploads")
    async def upload(
        key: str, file: UploadFile = File(...), synthetic: bool = Form(False)
    ):
        directory = engine.projects.directory(key)
        suffix = Path(file.filename or "").suffix.lower()
        allowed = {
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".glb",
            ".gltf",
            ".obj",
            ".json",
            ".blend",
        }
        if suffix not in allowed:
            raise ValueError(
                "Supported: PNG/JPEG/WebP references; GLB/GLTF/OBJ/JSON analysis; Blender scenes."
            )
        reference = suffix in {".png", ".jpg", ".jpeg", ".webp"}
        budget = (
            1500000 if reference else (128 if suffix == ".blend" else 32) * 1024 * 1024
        )
        path = directory / (uuid.uuid4().hex + suffix)
        size = 0
        try:
            with path.open("xb") as stream:
                while chunk := await file.read(64000):
                    size += len(chunk)
                    if size > budget:
                        raise ValueError(
                            "Upload exceeds this format's analysis budget."
                        )
                    stream.write(chunk)
            if reference:
                with Image.open(path) as opened:
                    if opened.width * opened.height > 16000000 or opened.format not in {
                        "PNG",
                        "JPEG",
                        "WEBP",
                    }:
                        raise ValueError("Unsupported image or pixel budget exceeded.")
                    expected = {
                        ".png": "PNG",
                        ".jpg": "JPEG",
                        ".jpeg": "JPEG",
                        ".webp": "WEBP",
                    }[suffix]
                    if opened.format != expected:
                        raise ValueError(
                            "Image extension does not match its decoded format."
                        )
                    opened.verify()
            else:
                await engine.ingest(key, path, synthetic)
            record = engine.projects.file(
                key,
                path,
                "reference" if reference else "source",
                Path((file.filename or "asset").replace("\\", "/")).name,
            )
            return {k: v for k, v in record.items() if k != "path"}
        except Exception:
            path.unlink(missing_ok=True)
            raise
        finally:
            await file.close()

    @app.post("/api/projects/{key}/build", status_code=202)
    async def build(key: str, value: BuildInput):
        job = await engine.build(key, value.asset_id)
        return {"id": job["id"], "status": job["status"]}

    @app.post("/api/projects/{key}/runs/{identifier}/{command}")
    async def control(
        key: str,
        identifier: str,
        command: Literal["pause", "cancel", "resume", "reconcile"],
    ):
        engine.projects.require_link(key, "production", identifier)
        if command in {"pause", "cancel"}:
            value = engine.domain.production.repository.request(identifier, command)
        elif command == "reconcile":
            async with engine.commands:
                engine.require_compute_available()
                value = await engine.production.reconcile(identifier)
        else:
            async with engine.commands:
                engine.require_compute_available()
                value = await engine.production.start(identifier)
        return {"id": value["id"], "status": value["status"]}

    @app.put("/api/projects/{key}/best")
    async def best(key: str, value: BestInput):
        engine.projects.require_link(key, "production", value.run_id)
        job = engine.domain.production.repository.get(value.run_id)
        if job["status"] != "completed_partial" or not job.get("application", {}).get(
            "export_readback", {}
        ).get("verified"):
            raise ValueError(
                "Only technically verified exported versions may be selected as project best."
            )
        return engine.projects.update(key, {"best_run": value.run_id})

    @app.get("/api/projects/{key}/files/{identifier}")
    async def artifact(key: str, identifier: str, download: bool = False):
        path, value = engine.projects.resolve_file(key, identifier)
        return FileResponse(
            path,
            filename=path.name if download else None,
            media_type="model/gltf-binary" if path.suffix == ".glb" else None,
        )

    @app.post("/api/projects/{key}/export")
    async def export(key: str):
        snapshot = await asyncio.to_thread(engine.snapshot, key)
        selected = snapshot["project"]["best_run"]
        candidates = [r for r in snapshot["runs"] if r["status"] == "completed_partial"]
        if not selected and candidates:
            selected = candidates[-1]["id"]
        if not selected:
            raise ValueError("No verified production version is available to export.")
        files = [
            f
            for f in engine.projects.files(key)
            if f["run_id"] == selected
            and f["kind"]
            in {"blend", "glb", "render", "front", "back", "flow", "verification"}
        ]
        if sum(f["bytes"] for f in files) > 256 * 1024 * 1024:
            raise ValueError("Project export exceeds 256 MiB budget.")
        destination = engine.projects.directory(key) / (
            uuid.uuid4().hex + "-export.zip"
        )
        manifest = {
            "product": "FORM",
            "schema": 1,
            "project": snapshot["project"],
            "selected_version": selected,
            "scope": "Technical validation only; artistic quality not certified.",
            "files": [],
            "source_provenance": [
                {"id": a["id"], "source": a["source"]} for a in snapshot["assets"]
            ],
            "version_evidence": next(
                r for r in snapshot["runs"] if r["id"] == selected
            ),
        }

        def package():
            with zipfile.ZipFile(destination, "x", zipfile.ZIP_DEFLATED) as archive:
                for item in files:
                    path, _ = engine.projects.resolve_file(key, item["id"])
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                    archive.write(path, path.name)
                    manifest["files"].append(
                        {"name": path.name, "sha256": digest, "kind": item["kind"]}
                    )
                archive.writestr("manifest.json", json.dumps(manifest, indent=2))

        await asyncio.to_thread(package)
        value = engine.projects.file(
            key, destination, "export", "Project bundle", selected
        )
        return {k: v for k, v in value.items() if k != "path"}

    @app.post("/api/projects/{key}/training", status_code=202)
    async def train(key: str, value: TrainingRequest):
        engine.projects.get(key)
        for asset in value.source_asset_ids:
            engine.projects.require_link(key, "asset", asset)
        async with engine.commands:
            engine.require_compute_available()
            if engine.shape.worker and not engine.shape.worker.done():
                raise ValueError("Wait for local shape inference before training.")
            if engine.appearance.worker and not engine.appearance.worker.done():
                raise ValueError("Pause visual practice before starting rig training.")
            host = engine.domain.training_host
            if host.worker and not host.worker.done():
                raise ValueError("An intentional training run is already active.")
            run = engine.domain.training.create(value)
            engine.projects.link(key, "training", run["id"])
            await host.start(run["id"])
        return {"id": run["id"], "status": run["status"]}

    @app.post("/api/projects/{key}/training/{identifier}/{command}")
    async def training_control(
        key: str, identifier: str, command: Literal["pause", "cancel", "resume"]
    ):
        engine.projects.require_link(key, "training", identifier)
        if command == "resume":
            async with engine.commands:
                engine.require_compute_available()
                return await engine.domain.training_host.start(identifier)
        return engine.domain.training.repository.request(identifier, command)

    @app.get("/api/projects/{key}/learning")
    async def learning(key: str, query: str = "character rig skin weights"):
        engine.projects.get(key)
        runs = engine.projects.links(key, "training")
        return {
            "knowledge": engine.domain.knowledge.search(query[:500], 12),
            "methods": engine.domain.training.repository.champions(),
            "appearance": engine.projects.get(key).get("visual_lab"),
            "visual_evaluations": engine.projects.get(key).get(
                "visual_evaluations", []
            ),
            "production_lessons": engine.domain.production.repository.lessons(),
            "exercises": [
                e for r in runs for e in engine.domain.training.repository.exercises(r)
            ],
            "attempts": [
                a
                for r in runs
                for a in engine.domain.training.repository.attempts(run_id=r, limit=100)
            ],
        }

    @app.post("/api/projects/{key}/learning/export")
    async def export_learning(key: str):
        engine.projects.get(key)

        def build_dataset():
            value = {
                "schema": "form-project-evidence-1",
                "project_id": key,
                "synthetic_included_explicitly": True,
                "appearance": engine.projects.get(key).get("visual_lab"),
                "visual_evaluations": engine.projects.get(key).get(
                    "visual_evaluations", []
                ),
                "scope": "Measured synthetic experience, not professionally certified training labels.",
                "training": [
                    engine.domain.training.dataset(r, include_synthetic=True, limit=100)
                    for r in engine.projects.links(key, "training")
                ],
                "production": [
                    engine.domain.production.dataset(r)
                    for r in engine.projects.links(key, "production")
                ],
            }
            data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
            if len(data) > 64 * 1024 * 1024:
                raise ValueError("Learning export exceeds bounded dataset budget.")
            path = engine.projects.directory(key) / (
                uuid.uuid4().hex + "-learning.json"
            )
            path.write_bytes(data)
            record = engine.projects.file(
                key, path, "dataset", "Project learning evidence"
            )
            return {k: v for k, v in record.items() if k != "path"}

        return await asyncio.to_thread(build_dataset)

    @app.post("/api/projects/{key}/shape", status_code=202)
    async def shape(key: str, value: ShapeInput):
        return await engine.shape.start(key, value.reference_id, value.quality)

    @app.post("/api/projects/{key}/visual/assess")
    async def assess(key: str, value: AssessmentInput):
        return await asyncio.to_thread(
            engine.appearance.assess, key, value.run_id, value.reference_id
        )

    @app.post("/api/projects/{key}/visual/practice", status_code=202)
    async def visual_practice(key: str, value: VisualInput):
        return await engine.appearance.start(key, value.reference_id, value.attempts)

    @app.post("/api/projects/{key}/visual/{command}")
    async def visual_control(key: str, command: Literal["pause", "cancel", "resume"]):
        if command == "resume":
            return await engine.appearance.start(key, None, resume=True)
        return engine.appearance.control(key, command)

    @app.post("/api/shutdown")
    async def shutdown():
        if shutdown_callback:
            shutdown_callback()
        return {"stopping": True}

    app.mount("/", StaticFiles(directory=web, html=True), name="product")
    return app
