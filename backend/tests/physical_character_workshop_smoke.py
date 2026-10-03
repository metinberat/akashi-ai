"""Short actual Blender improvement/readback/deformation integration. SYNTHETIC ONLY."""
import asyncio
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

from app.autonomy.knowledge import KnowledgeStore
from app.core.config import Settings
from app.devices.store import DeviceStore
from app.expertise.blender_workflow import BlenderWorkshopWorkflow
from app.expertise.schema import Source
from app.expertise.service import CharacterExpertiseService
from app.expertise.store import ExpertiseStore
from app.expertise.workshop.contracts import WorkshopRequest
from app.live.desktop import DesktopActionGateway

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/"desktop"/"agent"))
from akashi_agent.actions import ActionExecutor
from akashi_agent.config import AgentSettings


@asynccontextmanager
async def isolated_http_agent(root, environment):
    # This test owns one isolated loopback child, never the user's running Agent.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    origin, token = "http://127.0.0.1:%s" % port, secrets.token_hex(32)
    environment = {**environment, "PYTHONPATH": str(Path(__file__).resolve().parents[2]/"desktop"/"agent"),
        "AKASHI_AGENT_TOKEN": token, "AKASHI_AGENT_ALLOWED_ROOTS": str(root),
        "AKASHI_AGENT_CAPTURE_DIR": str(root/"captures"), "AKASHI_AGENT_CREDENTIAL_FILE": str(root/"device.credential"),
        "AKASHI_BROWSER_PROFILE_DIR": str(root/"browser-profile"), "AKASHI_AGENT_TIMEOUT": "90"}
    child = subprocess.Popen([sys.executable, "-m", "uvicorn", "akashi_agent.main:app", "--host", "127.0.0.1", "--port", str(port), "--no-access-log"],
        shell=False, env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    try:
        async with httpx.AsyncClient(base_url=origin, timeout=1, follow_redirects=False) as client:
            for _ in range(100):
                if child.poll() is not None:
                    raise RuntimeError("Isolated synthetic Agent failed to start.")
                try:
                    if (await client.get("/health")).status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                await asyncio.sleep(.1)
            else:
                raise RuntimeError("Isolated synthetic Agent startup timed out.")
            assert (await client.get("/v1/capabilities")).status_code == 401
            assert (await client.get("/v1/capabilities", headers={"Authorization": "Bearer "+token})).status_code == 200
        settings = Settings(local_agent_base_url=origin, local_agent_token=token, local_agent_timeout_seconds=105)
        gateway = DesktopActionGateway(settings, DeviceStore(root/"devices.json", 600, 75))
        yield gateway
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                await asyncio.to_thread(child.wait, 10)
            except subprocess.TimeoutExpired:
                child.kill()
                await asyncio.to_thread(child.wait, 10)


async def run_workshop(root, project, gateway):
    original_hash = hashlib.sha256(project.read_bytes()).hexdigest()
    observed = root/"observed.json"
    await gateway.execute("blender_operation", {"operation": "inspect_character", "project": str(project), "output": str(observed)}, approved=True)
    service = CharacterExpertiseService(ExpertiseStore(root/"expertise.sqlite3"), KnowledgeStore(root/"knowledge.json"))
    source = Source(reference="synthetic:locally-generated-Blender-limb", category="synthetic_fixture", synthetic=True)
    asset = service.ingest("observed.json", observed.read_bytes(), source)
    job = service.workshop.create(WorkshopRequest(asset_id=asset["id"]))

    class CountingTransport:
        staged_chunks = 0
        async def execute(self, action, arguments, approved):
            if arguments.get("operation") == "stage_weights":
                self.staged_chunks += 1
            return await gateway.execute(action, arguments, approved)

    transport = CountingTransport()
    refinement = await BlenderWorkshopWorkflow(transport, service.workshop).refine(job["id"], str(project), str(root))
    assert refinement["status"] == "verified", refinement
    result = refinement["cycles"][-1]
    finished = service.workshop.repository.get(job["id"])
    best = service.workshop.repository.version(finished["best_version"])
    assert best["id"] != job["baseline_version"], "No numeric improvement accepted"
    assert result["evidence"]["accepted"], result["evidence"]["reasons"]
    assert hashlib.sha256(project.read_bytes()).hexdigest() == original_hash
    output = result["evidence"]["artifacts"]["output"]
    # Actual rendered output exists, but this fabricated limb is not a professional character.
    render = root/"SYNTHETIC-best-render.png"
    await gateway.execute("blender_operation", {"operation": "render_current", "project": output, "output": str(render), "timeout_seconds": 90}, approved=True)
    versions = service.workshop.repository.versions(job["id"])
    def mean_strain(label):
        poses = result["evidence"][label]["poses"]
        return sum(p["mean_log_strain"] for p in poses)/len(poses)
    report = {"status": "WORKING", "synthetic": True, "asset_id": asset["id"], "job_id": job["id"],
        "baseline_score": versions[0]["evaluation"]["score"], "best_score": best["evaluation"]["score"],
        "attempts": finished["attempts"], "accepted": sum(v["decision"]["accepted"] for v in versions[1:]),
        "rejected": sum(not v["decision"]["accepted"] for v in versions[1:]),
        "actual_application_poses": len(result["evidence"]["after"]["poses"]), "saved_weight_readback": True,
        "application_strain_before": mean_strain("before"), "application_strain_after": mean_strain("after"),
        "staged_chunks": transport.staged_chunks, "patch_bytes": Path(result["evidence"]["artifacts"]["patch"]).stat().st_size,
        "transport": "authenticated_loopback_http_real_agent", "unauthenticated_agent_rejected": True,
        "application_verification_cycles": len(refinement["cycles"]),
        "source_hash_preserved": True, "best_checkpoint": result["best_version"], "output_blend": output, "render": str(render),
        "professional_character_analyzed": False, "quality_scope": "numeric_pose_tests_only"}
    (root/"report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
    return 0


async def main():
    root = Path("data/private/v31-validation")/uuid.uuid4().hex[:12]
    root = root.resolve()
    root.mkdir(parents=True)
    executor = ActionExecutor(AgentSettings(token="synthetic-test-only", allowed_roots=(root,), capture_dir=root/"captures", credential_file=root/"credential", action_timeout_seconds=90))
    blender = executor.apps.get("blender")
    if not blender:
        print(json.dumps({"status": "BLOCKED", "reason": "Blender not installed"}))
        return 2
    project = root/"SYNTHETIC-original.blend"
    script = Path(__file__).parent/"fixtures"/"create_workshop_blender.py"
    environment = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "PATH", "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA") if key in os.environ}
    created = subprocess.run([blender, "--disable-autoexec", "--background", "--factory-startup", "--python", str(script.resolve()), "--", str(project)], shell=False, env=environment, capture_output=True, timeout=90)
    if created.returncode or not project.is_file():
        raise RuntimeError("Synthetic fixture creation failed: " + (created.stdout+created.stderr).decode(errors="replace")[-2000:])
    async with isolated_http_agent(root, environment) as gateway:
        return await run_workshop(root, project, gateway)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
