"""Real local-only DCC/image-practice test, plus optional installed shape SDK.

No downloaded or professional character. Reference is our own synthetic render.
All generated outputs stay in .validation; external provider credentials are not read.
"""

import asyncio
import json
import os
from pathlib import Path

from form_studio.engine import Engine

ROOT = Path(__file__).resolve().parents[1]


async def main():
    os.environ["FORM_EXTERNAL_MODELS_ENABLED"] = "false"
    os.environ["FORM_VISION_PROVIDER"] = ""
    os.environ["FORM_REASONING_PROVIDER"] = ""
    report = json.loads((ROOT / ".validation/app-smoke-report.json").read_text())
    original = Engine(
        Path(
            os.getenv(
                "FORM_TEST_SOURCE_DATA", str(ROOT / ".validation/physical-project")
            )
        )
    )
    source = original.domain.production.repository.get(report["run"])
    assert source["status"] == "completed_partial"
    raw = Path(source["application"]["paths"]["front"]).read_bytes()
    assert len(raw) < 1500000
    e = Engine(ROOT / ".validation/local-quality")
    project = e.projects.create(
        "Synthetic local quality / provider-disabled",
        "Refine this synthetic frontal character locally; preserve the complete finger rig.",
    )
    key = project["id"]
    reference = e.projects.directory(key) / "synthetic-front-reference.png"
    reference.write_bytes(raw)
    record = e.projects.file(
        key, reference, "reference", "SYNTHETIC / own Blender front render"
    )
    reply, evidence = await e.propose(
        key,
        "Create a reference character with a professional face and local HUD",
        False,
    )
    assert evidence["model_status"] == "not_requested"
    assert evidence["local_observations"]["mask_status"] == "measured"
    design = dict(
        source["request"]["design"],
        cloth_color=[0.65, 0.05, 0.03],
        appearance="atelier",
    )
    e.projects.update(key, {"design": design})
    lab = await e.appearance.start(key, record["id"], 2)
    await e.appearance.worker
    lab = e.projects.get(key)["visual_lab"]
    assert lab["status"] == "completed", lab
    assert len(lab["attempts"]) == 2
    assert lab["best"]["loss"] <= min(a["evaluation"]["loss"] for a in lab["attempts"])
    snapshot = e.snapshot(key)
    for r in snapshot["runs"]:
        assert r["status"] == "completed_partial"
        assert r["features"]["joints"] == 57
        assert r["features"]["verified"]
    assert e.domain.knowledge.search("appearance practice", 5)
    result = {
        "project": key,
        "external_providers_enabled": False,
        "all_models_disabled_for_core_test": True,
        "reference_provenance": "our own synthetic Blender render, not a professional asset",
        "local_reference": evidence,
        "appearance_practice": lab,
        "runs": [
            {"id": r["id"], "status": r["status"], "joints": r["features"]["joints"]}
            for r in snapshot["runs"]
        ],
        "professional_quality_validated": False,
    }
    if os.getenv("FORM_TEST_SHAPE") == "1":
        job = await e.shape.start(key, record["id"], "draft")
        await e.shape.worker
        job = e.projects.get(key)["shape_jobs"][-1]
        assert job["status"] == "completed_partial", job
        result["learned_shape"] = job
        shape, _ = e.projects.resolve_file(key, job["output"])
        try:
            await e.ingest(key, shape, True)
        except ValueError:
            result["license_quarantine_verified"] = True
        else:
            raise AssertionError("Restricted output entered training ingestion")
    await e.shutdown()
    restored = Engine(e.root).snapshot(key)
    assert restored["project"]["visual_lab"]["best"]["run_id"] == lab["best"]["run_id"]
    result["reopen_persistence"] = True
    name = (
        "local-quality-report.json"
        if os.getenv("FORM_TEST_SHAPE") == "1"
        else "local-core-report.json"
    )
    output = ROOT / ".validation" / name
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "passed",
                "project": key,
                "visual_losses": [a["evaluation"]["loss"] for a in lab["attempts"]],
                "shape": result.get("learned_shape", {}).get("status", "not_requested"),
                "report": str(output),
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
