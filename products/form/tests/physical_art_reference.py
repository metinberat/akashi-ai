"""Local inference using the user's earlier supplied, user-owned 2D artwork.

Not a professional 3D asset, not downloaded and never sent to an external API.
"""

import asyncio
import json
import sys
from pathlib import Path
from PIL import Image, ImageOps
from form_studio.engine import Engine


async def main(source):
    root = Path(__file__).resolve().parents[1]
    e = Engine(root / ".validation/local-quality")
    p = e.projects.create(
        "AKASHI artwork / local learned shape",
        "User-owned 2D character artwork. Local geometry proposal; no professional asset or recovered rig is claimed.",
    )
    output = e.projects.directory(p["id"]) / "user-art-reference.png"
    with Image.open(source) as img:
        img = ImageOps.exif_transpose(img).convert("RGBA")
        img.thumbnail((640, 800))
        img.save(output, format="PNG")
    assert output.stat().st_size <= 1500000
    record = e.projects.file(
        p["id"],
        output,
        "reference",
        "USER-OWNED 2D ARTWORK / not a supplied professional 3D asset",
    )
    job = await e.shape.start(p["id"], record["id"], "quality")
    await e.shape.worker
    job = e.projects.get(p["id"])["shape_jobs"][-1]
    assert job["status"] == "completed_partial", job
    result = {
        "project": p["id"],
        "user_owned_2d_artwork": True,
        "professional_3d_asset": False,
        "external_api_used": False,
        "new_models_downloaded": False,
        "learned_shape": job,
        "professional_quality_validated": False,
    }
    (root / ".validation/art-reference-report.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    await e.shutdown()
    print(
        json.dumps(
            {
                "status": "passed",
                "project": p["id"],
                "vertices": job["evidence"]["vertices"],
                "segmentation": job["evidence"]["reference_preprocessing"]["method"],
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
