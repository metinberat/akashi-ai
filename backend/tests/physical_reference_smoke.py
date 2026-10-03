"""Optional configured vision on OUR generated render; prints no credentials/raw image."""

import argparse
import asyncio
import base64
import json
from pathlib import Path
from app.core.config import get_settings
from app.core.model_router import ModelRouter
from app.expertise.production.contracts import BuildRequest
from app.expertise.production.reference import ReferenceIntelligence


async def main(path):
    path = Path(path).resolve()
    image = "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()
    request, evidence = await ReferenceIntelligence(
        ModelRouter(get_settings())
    ).resolve(
        BuildRequest(
            brief="Interpret this SYNTHETIC generated humanoid and propose a supported stylized design; do not claim accurate hidden geometry.",
            reference_image=image,
            use_models=True,
        )
    )
    result = {
        "synthetic": True,
        "reference": evidence,
        "proposed_design": request.design.model_dump() if request.design else None,
    }
    output = path.with_name("reference-intelligence-report.json")
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(output), **result}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    asyncio.run(main(parser.parse_args().image))
