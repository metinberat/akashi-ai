"""Explicit reconciliation/reopen of our own interrupted synthetic test artifact."""

import argparse
import asyncio
import json
import os
from pathlib import Path
from app.autonomy.knowledge import KnowledgeStore
from app.expertise.service import CharacterExpertiseService
from app.expertise.store import ExpertiseStore
from app.expertise.production.host import ProductionHost
from tests.physical_character_workshop_smoke import isolated_http_agent


async def main(directory):
    root = Path(directory).resolve()
    service = CharacterExpertiseService(
        ExpertiseStore(root / "expert.sqlite3"), KnowledgeStore(root / "knowledge.json")
    )
    job = service.production.repository.list()[0]
    original = job["active_application"]["paths"]["blend"]
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
        host = ProductionHost(service.production, gateway)
        reconciled = await host.reconcile(job["id"])
        assert reconciled["status"] == "paused"
        assert reconciled["active_application"]["paths"]["blend"] == original
        result = await host.run(job["id"])
        assert result["status"] == "completed_partial"
        assert result["application"]["paths"]["blend"] == original
        assert (
            result["application"]["build"]["scope"]
            == "reopened and compared, not replayed"
        )
    (root / "recovery-report.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "report": str(root / "recovery-report.json"),
                "status": result["status"],
                "build_not_replayed": True,
                "paths": result["application"]["paths"],
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    asyncio.run(main(parser.parse_args().directory))
