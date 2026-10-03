"""Manual end-to-end smoke test for real Windows window/input primitives."""
from __future__ import annotations

import os
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from akashi_agent.windows import computer_input, control_window, list_windows


def main() -> int:
    if sys.platform != "win32":
        print("BLOCKED: Windows required")
        return 2
    fixture = Path(__file__).parent / "fixtures" / "input_harness.py"
    output = Path(tempfile.gettempdir()) / "akashi-native-input-smoke.txt"
    output.unlink(missing_ok=True)
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
    try:
        window = None
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            window = next(
                (item for item in list_windows(200)["windows"] if item["title"] == "AKASHI Computer Agent Input Harness"),
                None,
            )
            if window:
                break
            time.sleep(0.1)
        if not window:
            raise RuntimeError("Harness window did not open.")
        focused = control_window({"operation": "focus", "window_id": window["window_id"]})
        if not focused["verified"]:
            raise RuntimeError("Harness focus could not be verified.")
        moved = control_window({
            "operation": "move", "window_id": window["window_id"],
            "x": 240, "y": 140, "width": 760, "height": 430,
        })
        if not moved["verified"]:
            raise RuntimeError("Harness move could not be verified.")
        minimized = control_window({"operation": "minimize", "window_id": window["window_id"]})
        if not minimized["verified"]:
            raise RuntimeError("Harness minimize could not be verified.")
        restored = control_window({"operation": "restore", "window_id": window["window_id"]})
        if not restored["verified"]:
            raise RuntimeError("Harness restore could not be verified.")
        focused = control_window({"operation": "focus", "window_id": window["window_id"]})
        if not focused["verified"]:
            raise RuntimeError("Harness refocus could not be verified.")
        window = next(item for item in list_windows(200)["windows"] if item["window_id"] == window["window_id"])
        expected = "AKASHI native input verified — Türkçe: çalışıyor."
        computer_input({"operation": "type_text", "text": expected})
        computer_input({"operation": "shortcut", "keys": ["ctrl", "a"]})
        computer_input({"operation": "type_text", "text": expected})
        bounds = window.get("client_bounds") or window["bounds"]
        x = int(bounds["x"] + bounds["width"] * 0.50)
        y = int(bounds["y"] + bounds["height"] - 45)
        computer_input({"operation": "click", "x": x, "y": y})
        computer_input({"operation": "double_click", "x": x + 30, "y": y})
        computer_input({"operation": "right_click", "x": x + 60, "y": y})
        computer_input({"operation": "drag", "x": x - 80, "y": y, "x2": x + 80, "y2": y})
        computer_input({"operation": "scroll", "delta": -240})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if output.is_file():
                observed = json.loads(output.read_text(encoding="utf-8"))
                required = {"click", "double_click", "right_click", "drag", "scroll"}
                if observed.get("text") == expected and required.issubset(set(observed.get("events") or [])):
                    print("WORKING: window move/minimize/restore/focus plus Unicode typing, shortcut, click/double/right, drag and scroll verified")
                    return 0
            time.sleep(0.1)
        raise RuntimeError("Typed text was not observed by the target application.")
    finally:
        current = next(
            (item for item in list_windows(200)["windows"] if item["title"] == "AKASHI Computer Agent Input Harness"),
            None,
        )
        if current:
            control_window({"operation": "close", "window_id": current["window_id"]})
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.terminate()
        output.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
