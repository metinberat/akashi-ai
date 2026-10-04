"""Start a real AKASHI Core for the Spatial Lab browser suite.

Builds a FORM library with FORM's own project code (products/form/server) and
the shared production repository, containing SYNTHETIC GLBs (not real FORM
characters), then serves app.main on 127.0.0.1:8017 with the mock text model
and the deterministic spatial rules interpreter.
"""

import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO / "backend"), str(REPO / "products" / "form" / "server")]
TOKEN = "spatial-e2e-token-0000000000000000000000"
PORT = int(os.environ.get("SPATIAL_E2E_CORE_PORT", "8017"))


def build_form_library(root: Path) -> None:
    from app.expertise.production.contracts import BuildRequest
    from app.expertise.production.repository import ProductionRepository
    from app.expertise.store import ExpertiseStore, encode
    from app.spatial.fixtures import build_glb
    from form_studio.projects import Projects

    store = ExpertiseStore(root / "expert.sqlite3")
    production = ProductionRepository(store)
    projects = Projects(store, root / "projects")
    project = projects.create("Hero Prototype", "synthetic e2e fixture")
    first = None
    for index, (size, verified) in enumerate((((0.5, 1.75, 0.3), True), ((0.55, 1.8, 0.32), False), ((0.6, 1.85, 0.32), True))):
        job = production.create(BuildRequest(brief="hero"), None, [])
        data = build_glb(size=size, center=(0, size[1] / 2, 0), skinned=True, joint_count=4, clips=("Idle", "Walk Cycle"),
                         hud_rings=3, form_style=True)
        outputs = projects.directory(project["id"]) / "outputs"
        outputs.mkdir(exist_ok=True)
        path = outputs / f"{job['id']}-character.glb"
        path.write_bytes(data)
        job.update(status="completed_partial" if verified else "paused_recovery", application={
            "paths": {"glb": str(path)}, "done": ["export", "export_readback"],
            "export_readback": {"verified": verified, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "skins": 1, "animations": 2}})
        with store.connection() as db:
            db.execute("UPDATE production_jobs SET body=? WHERE id=?", (encode(job), job["id"]))
        projects.link(project["id"], "production", job["id"])
        first = first or job["id"]
    projects.update(project["id"], {"best_run": first})
    # A second project whose version holds genuine FORM export content
    # (backend/tests/fixtures/form/README.md), registered with FORM's real schema.
    real = REPO / "backend" / "tests" / "fixtures" / "form" / "form-atelier-hud-seed57.glb"
    atelier = projects.create("Atelier Real Export", "real FORM geometry + Blender build/export")
    job = production.create(BuildRequest(brief="atelier"), None, [])
    outputs = projects.directory(atelier["id"]) / "outputs"
    outputs.mkdir(exist_ok=True)
    path = outputs / f"{job['id']}-character.glb"
    data = real.read_bytes()
    path.write_bytes(data)
    job.update(status="completed_partial", application={
        "paths": {"glb": str(path)}, "done": ["export", "export_readback"],
        "export_readback": {"verified": True, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "skins": 1, "animations": 4}})
    with store.connection() as db:
        db.execute("UPDATE production_jobs SET body=? WHERE id=?", (encode(job), job["id"]))
    projects.link(atelier["id"], "production", job["id"])


def main() -> None:
    root = Path(os.environ.get("SPATIAL_E2E_DATA") or tempfile.mkdtemp(prefix="akashi-spatial-e2e-"))
    if root.exists() and os.environ.get("SPATIAL_E2E_DATA"):
        shutil.rmtree(root)
    (root / "form").mkdir(parents=True)
    build_form_library(root / "form")
    os.environ.update({
        "AKASHI_API_TOKEN": TOKEN, "AI_PROVIDER": "mock", "AKASHI_DATA_DIR": str(root / "core"),
        "AKASHI_FORM_DATA_DIR": str(root / "form"), "AKASHI_SPATIAL_INTERPRETER": "rules",
        "AKASHI_CORS_ORIGINS": "http://localhost:3101,http://127.0.0.1:3101", "RESEARCH_PROVIDER": "duckduckgo",
    })
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
