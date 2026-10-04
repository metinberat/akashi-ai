"""Produce a real FORM character GLB for Spatial Lab validation.

Runs FORM's production geometry generator and the Windows Agent's fixed Blender
operations (stage_production → build_production → export_gltf →
inspect_production_export). Renders are skipped, so this is NOT a full FORM
production run and creates no FORM project records; it produces the same GLB
content FORM exports for that design.

    python scripts/form_spatial_probe.py <work dir> <blender executable>

On Windows pass the installed blender.exe. In environments without a Blender
binary, a shim around the PyPI `bpy` module can emulate the CLI (see
docs/spatial-lab.md, "Real FORM fixture").
"""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "desktop" / "agent")]

from akashi_agent.actions import ActionExecutor  # noqa: E402
from akashi_agent.config import AgentSettings  # noqa: E402
from app.expertise.production.contracts import Design  # noqa: E402
from app.expertise.production.geometry import construct  # noqa: E402
from app.spatial.glb import inspect  # noqa: E402


def main() -> int:
    work, blender = Path(sys.argv[1]).resolve(), sys.argv[2]
    work.mkdir(parents=True, exist_ok=True)
    executor = ActionExecutor(AgentSettings(token=None, allowed_roots=(work,), capture_dir=work / "captures",
                                            credential_file=work / "credential", action_timeout_seconds=300))
    executor.apps["blender"] = blender
    document = construct(Design(appearance="atelier", hud=True, height=1.8).model_dump(), {"radial": 16}, 57)
    payload = json.dumps(document, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode()
    digest = hashlib.sha256(payload).hexdigest()
    chunks = [payload[i:i + 24000].decode() for i in range(0, len(payload), 24000)]
    staged = work / "input.json"
    for index, chunk in enumerate(chunks):
        executor.execute("blender_operation", {"operation": "stage_production", "output": str(staged), "chunk": chunk,
                                               "chunk_index": index, "chunk_count": len(chunks), "sha256": digest}, approved=True)

    def run(**arguments):
        return executor.execute("blender_operation", arguments, approved=True)

    run(operation="build_production", project=str(staged), output=str(work / "character.blend"), timeout_seconds=300)
    run(operation="export_gltf", project=str(work / "character.blend"), output=str(work / "character.glb"), timeout_seconds=300)
    readback = run(operation="inspect_production_export", project=str(work / "character.glb"))
    spatial = inspect((work / "character.glb").read_bytes())
    print(json.dumps({"form_readback": readback, "spatial": {k: spatial[k] for k in ("joints", "clips", "form_hud_nodes", "normalization", "warnings")}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
