"""Manual real-model, real-agent, cross-application V2 acceptance smoke."""
from __future__ import annotations

import asyncio
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.core.absolute import AkashiCore
from app.core.config import get_settings


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return


async def run() -> int:
    repository = Path(__file__).resolve().parents[2]
    fixture = repository / "desktop" / "agent" / "tests" / "fixtures"
    handler = lambda *args, **kwargs: QuietHandler(*args, directory=str(fixture), **kwargs)  # noqa: E731
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    artifact = repository / "backend" / "data" / "private" / "v2-operator-physical.txt"
    artifact.unlink(missing_ok=True)
    url = f"http://127.0.0.1:{server.server_port}/browser_harness.html"
    try:
        core = AkashiCore(get_settings())
        goal = (
            f"Complete this objective from beginning to end. Open the isolated AKASHI browser at {url}. "
            "Using semantic browser controls, enter 'AKASHI V2 REAL WORKFLOW' into the Objective field and click "
            "Verify workflow. Observe and verify that the page visibly contains 'VERIFIED: AKASHI V2 REAL WORKFLOW'. "
            f"Then create the UTF-8 text file {artifact} containing that exact verified line, verify the file exists "
            "and contains the expected result, and report the verified browser URL and artifact path."
        )
        task = await core.autonomy.create(goal, "physical-v2-smoke", approved=True)
        result = await core.autonomy.wait(task["id"], timeout=300)
        content = artifact.read_text(encoding="utf-8") if artifact.is_file() else ""
        passed = result.get("status") == "completed" and "VERIFIED: AKASHI V2 REAL WORKFLOW" in content
        print(json.dumps({
            "status": "WORKING" if passed else "FAILED",
            "task_status": result.get("status"),
            "subgoals": [{"title": item.get("title"), "status": item.get("status"), "attempts": item.get("attempts")} for item in result.get("subgoals", [])],
            "artifact_exists": artifact.is_file(),
            "artifact_verified": "VERIFIED: AKASHI V2 REAL WORKFLOW" in content,
            "replans": result.get("replans"),
            "skill_candidate": bool(result.get("skill_candidate_id")),
            "summary": result.get("summary") or result.get("error"),
        }, ensure_ascii=False))
        return 0 if passed else 1
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
