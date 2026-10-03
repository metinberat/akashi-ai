"""Targeted real adapter execution on existing synthetic practice project."""

import asyncio
import json
from pathlib import Path
from form_studio.engine import Engine


async def main():
    root = Path(__file__).resolve().parents[1]
    e = Engine(root / ".validation/local-quality")
    p = next(
        p
        for p in e.projects.list()
        if p.get("visual_lab", {}).get("status") == "completed"
    )
    lab = p["visual_lab"]
    job = await e.shape.start(p["id"], lab["reference_id"])
    await e.shape.worker
    job = e.projects.get(p["id"])["shape_jobs"][-1]
    assert job["status"] == "completed_partial", job
    path, _ = e.projects.resolve_file(p["id"], job["output"])
    assert path.stat().st_size > 10000
    try:
        await e.ingest(p["id"], path, True)
    except ValueError:
        pass
    else:
        raise AssertionError("Vendor output entered training")
    result = {
        "project": p["id"],
        "appearance_practice": lab,
        "learned_shape": job,
        "cloud_enabled": False,
        "external_api_used": False,
        "synthetic_reference": True,
        "license_quarantine_verified": True,
        "professional_quality_validated": False,
        "reopen_persistence": False,
    }
    await e.shutdown()
    restored = Engine(e.root).projects.get(p["id"])
    assert restored["visual_lab"]["best"]["run_id"] == lab["best"]["run_id"]
    assert restored["shape_jobs"][-1]["output"] == job["output"]
    result["reopen_persistence"] = True
    (root / ".validation/local-quality-report.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "project": p["id"],
                "vertices": job["evidence"]["vertices"],
                "visual_losses": [a["evaluation"]["loss"] for a in lab["attempts"]],
                "quarantine": True,
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
