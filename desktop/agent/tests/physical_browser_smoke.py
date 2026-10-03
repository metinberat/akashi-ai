"""Physical CDP semantic browser + cross-application artifact smoke test."""
from __future__ import annotations

import json
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from akashi_agent.actions import ActionExecutor
from akashi_agent.config import AgentSettings


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> int:
    fixture = Path(__file__).parent / "fixtures"
    handler = lambda *args, **kwargs: QuietHandler(*args, directory=str(fixture), **kwargs)  # noqa: E731
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        settings = AgentSettings(
            token="physical-browser-smoke-token-000000000000",
            allowed_roots=(root,), capture_dir=root / "captures", credential_file=root / "credential",
            browser_profile_dir=Path.home() / "AppData/Local/AkashiAI/browser-v2-smoke",
            browser_debug_port=9333,
        )
        executor = ActionExecutor(settings)
        url = f"http://127.0.0.1:{server.server_port}/browser_harness.html"
        try:
            started = executor.execute("browser_start", {"url": url}, approved=True)["data"]
            tabs = executor.execute("browser_tabs", {})["data"]["tabs"]
            selected = next((item for item in tabs if item.get("url") == url), None)
            if selected is None:
                selected = executor.execute("browser_action", {"operation": "new_tab", "url": url}, approved=True)["data"]
                tab_id = selected["tab_id"]
            else:
                tab_id = selected["id"]
            snapshot = executor.execute("browser_snapshot", {"tab_id": tab_id})["data"]
            if snapshot.get("title") != "AKASHI V2 Browser Harness":
                raise RuntimeError(f"Unexpected browser title: {snapshot.get('title')}")
            executor.execute("browser_action", {
                "operation": "type", "tab_id": snapshot["tab_id"],
                "target": {"index": next(item["index"] for item in snapshot["elements"] if item.get("label") == "Objective")}, "value": "cross application artifact",
            }, approved=True)
            try:
                executor.execute("browser_action", {"operation": "click", "tab_id": tab_id, "target": {"text": "Duplicate target"}}, approved=True)
            except RuntimeError as exc:
                assert "Ambiguous" in str(exc)
            else:
                raise RuntimeError("Ambiguous locator was not rejected.")
            result = executor.execute("browser_action", {
                "operation": "click", "tab_id": snapshot["tab_id"], "target": {"role": "button", "text": "Verify workflow"},
            }, approved=True)["data"]
            text = str(result["snapshot"].get("text") or "")
            if "VERIFIED: cross application artifact" not in text:
                raise RuntimeError("DOM verification did not observe the expected result.")
            artifact = root / "browser-result.json"
            payload = json.dumps({"source": result["snapshot"]["url"], "result": "VERIFIED: cross application artifact"}, indent=2)
            created = executor.execute("file_operation", {
                "operation": "create_text", "destination": str(artifact), "content": payload,
            }, approved=True)["data"]
            metadata = executor.execute("file_metadata", {"path": str(artifact)})["data"]
            if not created.get("verified") or metadata.get("size", 0) <= 0:
                raise RuntimeError("Filesystem artifact verification failed.")
            executor.execute("reveal_file", {"path": str(artifact)}, approved=True)
            executor.execute("browser_action", {"operation": "close_tab", "tab_id": tab_id}, approved=True)
            print(json.dumps({
                "status": "WORKING", "browser_ready": started["verified"],
                "semantic_dom_verified": True, "artifact_verified": True,
                "cross_application": ["Chromium", "filesystem", "File Explorer"],
            }))
            return 0
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
