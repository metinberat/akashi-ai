"""Manual real-model OBSERVE→PLAN→ACT→VERIFY smoke test on a disposable UI."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict

from akashi_agent.actions import ActionExecutor
from akashi_agent.config import AgentSettings
from app.computer.service import ComputerAgentService
from app.computer.store import JSONComputerStateStore
from app.core.config import get_settings
from app.core.model_router import ModelRouter
from app.events.hub import EventHub


class LocalGateway:
    def __init__(self, executor: ActionExecutor) -> None:
        self.executor = executor

    async def execute(self, action: str, arguments: Dict[str, Any], approved: bool) -> Dict[str, Any]:
        return await asyncio.to_thread(self.executor.execute, action, arguments, approved)


async def main() -> int:
    if sys.platform != "win32":
        print("BLOCKED: Windows required")
        return 2
    root = Path(__file__).resolve().parents[2]
    fixture = root / "desktop" / "agent" / "tests" / "fixtures" / "input_harness.py"
    run_id = uuid.uuid4().hex[:10]
    output = Path(tempfile.gettempdir()) / f"akashi-computer-loop-smoke-{run_id}.json"
    state_path = Path(tempfile.gettempdir()) / f"akashi-computer-loop-state-{run_id}.json"
    output.unlink(missing_ok=True)
    state_path.unlink(missing_ok=True)
    environment = os.environ.copy()
    environment["AKASHI_INPUT_HARNESS_OUTPUT"] = str(output)
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    process = subprocess.Popen(
        [str(pythonw if pythonw.is_file() else sys.executable), str(fixture)],
        env=environment,
        shell=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    executor = ActionExecutor(AgentSettings.from_env())
    try:
        window = None
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            state = executor.execute("get_desktop_state", {"limit": 200})["data"]
            window = next((item for item in state["windows"] if item["title"] == "AKASHI Computer Agent Input Harness"), None)
            if window:
                break
            await asyncio.sleep(0.1)
        if not window:
            print("BLOCKED: harness did not open")
            return 3
        focused = executor.execute("window_control", {"operation": "focus", "window_id": window["window_id"]}, True)["data"]
        if not focused["verified"]:
            print("BLOCKED: harness focus failed")
            return 4
        service = ComputerAgentService(
            LocalGateway(executor),  # type: ignore[arg-type]
            ModelRouter(get_settings()),
            EventHub(),
            JSONComputerStateStore(state_path),
            max_steps=10,
        )
        expected = "AKASHI LOOP VERIFIED"
        result = await service.run(
            f"In the visible 'AKASHI Computer Agent Input Harness', click the large white text editor, type exactly '{expected}', then click the blue CLICK TARGET area. Stop only after the text and CLICK status are visible.",
            "physical-loop",
            approved=True,
        )
        observed = json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
        ok = observed.get("text") == expected and "click" in set(observed.get("events") or []) and result.get("status") == "completed"
        print(json.dumps({
            "status": "WORKING" if ok else "FAILED",
            "task_status": result.get("status"),
            "steps": [step.get("action") for step in result.get("steps", [])],
            "text_verified": observed.get("text") == expected,
            "click_verified": "click" in set(observed.get("events") or []),
            "summary": result.get("summary"),
        }, ensure_ascii=False))
        return 0 if ok else 6
    finally:
        state = executor.execute("get_desktop_state", {"limit": 200})["data"]
        current = next((item for item in state["windows"] if item["title"] == "AKASHI Computer Agent Input Harness"), None)
        if current:
            executor.execute("window_control", {"operation": "close", "window_id": current["window_id"]}, True)
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.terminate()
        output.unlink(missing_ok=True)
        state_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
