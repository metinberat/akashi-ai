"""Dev-only: spawn live.py like Electron and print events (no secrets)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from queue import Empty, Queue

ROOT = Path(__file__).resolve().parent
ENV_CANDIDATES = [
    Path(r"C:\Users\bigfa\OneDrive\Desktop\akashi-ai\backend\.env"),
    Path(r"C:\Users\bigfa\OneDrive\Desktop\akashi-ai\.env"),
    Path(r"C:\Users\bigfa\OneDrive\Desktop\akashi-ai\.tmp-absolute\Absolute\.env"),
]


def read_key() -> str:
    for path in ENV_CANDIDATES:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("GEMINI_API_KEY="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value:
                    return value
    raise SystemExit("no gemini key found")


def bounded_env() -> dict[str, str]:
    allowed = [
        "SystemRoot", "WINDIR", "PATH", "PATHEXT", "TEMP", "TMP", "USERPROFILE",
        "LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "COMSPEC",
    ]
    output = {name: os.environ[name] for name in allowed if name in os.environ}
    output["PYTHONUNBUFFERED"] = "1"
    output["PYTHONIOENCODING"] = "utf-8"
    return output


def pump(stream, q: Queue) -> None:
    for line in stream:
        q.put(line)
    q.put(None)


def main() -> int:
    handshake = {
        "gemini_api_key": read_key(),
        "core_base_url": "",
        "core_token": "",
        "voice_name": "Charon",
        "language": "auto",
        "identity": "You are AKASHI.",
        "voice_style": "Keep replies brief.",
    }
    child = subprocess.Popen(
        [sys.executable, str(ROOT / "live.py")],
        cwd=str(ROOT),
        env=bounded_env(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert child.stdin and child.stdout and child.stderr
    child.stdin.write(json.dumps(handshake) + "\n")
    child.stdin.flush()
    out_q: Queue = Queue()
    err_q: Queue = Queue()
    threading.Thread(target=pump, args=(child.stdout, out_q), daemon=True).start()
    threading.Thread(target=pump, args=(child.stderr, err_q), daemon=True).start()
    events = []
    deadline = time.monotonic() + 18
    try:
        while time.monotonic() < deadline:
            try:
                line = out_q.get(timeout=0.2)
            except Empty:
                continue
            if line is None:
                break
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                print("NONJSON", line[:200])
                continue
            kind = payload.get("event")
            msg = str(payload.get("message") or payload.get("state") or payload.get("text") or "")[:180]
            print("EVENT", kind, msg)
            events.append(kind)
            if kind == "error" and not payload.get("transient"):
                break
    finally:
        try:
            child.stdin.write(json.dumps({"cmd": "stop"}) + "\n")
            child.stdin.flush()
        except Exception:
            pass
        try:
            child.kill()
        except Exception:
            pass
        err_bits = []
        while True:
            try:
                chunk = err_q.get_nowait()
            except Empty:
                break
            if chunk:
                err_bits.append(chunk)
        err = "".join(err_bits)
        if err:
            print("STDERR", err[-2500:])
    return 0 if "ready" in events else 2


if __name__ == "__main__":
    raise SystemExit(main())
