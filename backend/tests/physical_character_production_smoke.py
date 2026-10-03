"""Real bounded humanoid authoring/render/export. All characters are locally synthetic."""

import asyncio
import argparse
import base64
import json
import os
import uuid
from pathlib import Path
from app.expertise.service import CharacterExpertiseService
from app.expertise.store import ExpertiseStore
from app.autonomy.knowledge import KnowledgeStore
from app.expertise.production.contracts import BuildRequest, Design
from app.expertise.production.host import ProductionHost
from app.expertise.production.reference import ReferenceIntelligence
from app.core.config import get_settings
from app.core.model_router import ModelRouter
from app.expertise.parsers import parse_asset
from tests.physical_character_workshop_smoke import isolated_http_agent


async def main(reference=None):
    root = (
        Path("data/private/production-validation") / uuid.uuid4().hex[:12]
    ).resolve()
    root.mkdir(parents=True)
    service = CharacterExpertiseService(
        ExpertiseStore(root / "expert.sqlite3"), KnowledgeStore(root / "knowledge.json")
    )
    request = BuildRequest(
        brief="SYNTHETIC stylized humanoid with character-attached energy rings",
        design=None if reference else Design(hud=True, clothing="coat"),
        output_directory=str(root),
        reference_image="data:image/png;base64,"
        + base64.b64encode(Path(reference).read_bytes()).decode()
        if reference
        else None,
        use_models=bool(reference),
    )
    evidence = None
    if reference:
        request, evidence = await ReferenceIntelligence(
            ModelRouter(get_settings())
        ).resolve(request)
        assert evidence["model_status"] == "interpreted", evidence
    job = service.production.create(request, evidence)
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
        result = await ProductionHost(service.production, gateway).run(job["id"])
        assert result["status"] == "completed_partial", result
        assert result["application"]["readback"]["verified"]
        assert result["application"]["features"]["hud"]
        assert result["application"]["export_readback"]["skins"]
        assert result["application"]["export_readback"]["animations"]
        glb = Path(result["application"]["paths"]["glb"])
        imported, _ = parse_asset(glb.name, glb.read_bytes())
        assert len(imported.joints) == 57 and imported.animations
        assert any(m.metadata["morph_target_deltas"] for m in imported.meshes)
        assert result["application"]["learned_asset_id"]
    report = {
        "synthetic": True,
        "professional_asset_analyzed": False,
        "job_id": job["id"],
        "status": result["status"],
        "trials": len(service.production.repository.trials(job["id"])),
        "numeric": result["best"]["evaluation"],
        "application": result["application"],
        "remaining": result["remaining"],
        "reference": evidence,
        "glb_reingestion": {
            "joints": len(imported.joints),
            "meshes": len(imported.meshes),
            "animations": len(imported.animations),
        },
    }
    (root / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "report": str(root / "report.json"),
                "render": result["application"]["paths"]["render"],
                "blend": result["application"]["paths"]["blend"],
                "status": result["status"],
                "joints": result["application"]["features"]["joints"],
                "meshes": result["application"]["features"]["meshes"],
                "export": result["application"]["export_readback"],
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference")
    asyncio.run(main(parser.parse_args().reference))
