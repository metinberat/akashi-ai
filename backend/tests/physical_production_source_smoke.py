"""Use an explicitly generated local character; never a downloaded professional asset."""

import argparse
import asyncio
import base64
import hashlib
import json
import os
import uuid
from pathlib import Path

from app.autonomy.knowledge import KnowledgeStore
from app.core.config import get_settings
from app.core.model_router import ModelRouter
from app.expertise.schema import Source
from app.expertise.service import CharacterExpertiseService
from app.expertise.store import ExpertiseStore
from app.expertise.production.contracts import BuildRequest
from app.expertise.production.host import ProductionHost
from app.expertise.production.reference import ReferenceIntelligence
from app.expertise.training.blender import TrainingBlenderAdapter
from tests.physical_character_workshop_smoke import isolated_http_agent


async def main(source, image, vision):
    source = Path(source).resolve()
    root = source.parent
    work = root / ("source-test-" + uuid.uuid4().hex[:8])
    work.mkdir()
    service = CharacterExpertiseService(
        ExpertiseStore(work / "expert.sqlite3"), KnowledgeStore(work / "knowledge.json")
    )
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    env = {
        k: os.environ[k]
        for k in (
            "SystemRoot",
            "WINDIR",
            "PATH",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "APPDATA",
            "LOCALAPPDATA",
        )
        if k in os.environ
    }
    async with isolated_http_agent(root, env) as gateway:
        adapter = TrainingBlenderAdapter(gateway, service)
        asset = await adapter.ingest_blender(
            str(source),
            str(work),
            Source(
                reference="synthetic:local-production-readback",
                category="synthetic_fixture",
                synthetic=True,
            ),
        )
        job = service.production.create(
            BuildRequest(
                source_asset_id=asset["id"],
                source_project=str(source),
                output_directory=str(work),
            )
        )
        result = await ProductionHost(service.production, gateway).run(job["id"])
        assert result["status"] == "completed_partial"
        assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    report = {
        "synthetic": True,
        "source_preserved": True,
        "status": result["status"],
        "application": result["application"],
    }
    if vision:
        payload = (
            "data:image/png;base64,"
            + base64.b64encode(Path(image).read_bytes()).decode()
        )
        _, evidence = await ReferenceIntelligence(ModelRouter(get_settings())).resolve(
            BuildRequest(
                brief="Inspect this locally generated synthetic humanoid and propose supported proportions, clothes, hair and spatial rings. Missing views are unknown.",
                reference_image=payload,
                use_models=True,
            )
        )
        report["reference_intelligence"] = evidence
    (work / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "report": str(work / "report.json"),
                "source_preserved": True,
                "mode": "presentation_only",
                "reference": report.get("reference_intelligence"),
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--image")
    parser.add_argument("--vision", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.source, args.image, args.vision))
