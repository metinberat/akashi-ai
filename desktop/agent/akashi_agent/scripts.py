"""Opt-in project execution, pinned by a locally configured package digest.

This is trusted-code execution, NOT a sandbox. Never register untrusted projects.
The remote caller cannot choose executable paths, command text or arguments.
"""
import hashlib
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict


def run_pinned_script(project: Path, package_file: Path, script: str, registry: Path,
                      timeout: int, output_limit: int) -> Dict[str, Any]:
    package_bytes = package_file.read_bytes()
    digest = hashlib.sha256(package_bytes).hexdigest()
    entries = json.loads(registry.read_text(encoding="utf-8")).get("scripts", [])
    if not any(Path(item.get("project", "")).resolve() == project and item.get("script") == script
               and item.get("package_sha256") == digest for item in entries):
        raise PermissionError("Project/script is not pinned in the local registry, or package.json changed.")
    package = json.loads(package_bytes)
    if script not in package.get("scripts", {}):
        raise ValueError("The pinned script no longer exists.")
    node = shutil.which("node.exe") or shutil.which("node")
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    npm_cli = Path(npm).parent / "node_modules/npm/bin/npm-cli.js" if npm else None
    if not node or not npm_cli or not npm_cli.is_file():
        raise RuntimeError("A Node installation with npm-cli.js is required; shell wrappers are not executed.")
    # Minimal environment: never inherit backend/provider/agent credentials.
    keep = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT", "USERPROFILE", "LOCALAPPDATA", "APPDATA"}
    env = {key: value for key, value in os.environ.items() if key.upper() in keep}
    env["CI"] = "1"
    process = subprocess.Popen([node, str(npm_cli), "--ignore-scripts", "run", script],
                               cwd=str(project), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               stdin=subprocess.DEVNULL, env=env, shell=False,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    output = bytearray()
    total = [0]

    def drain() -> None:
        assert process.stdout is not None
        while True:
            chunk = process.stdout.read(4096)
            if not chunk:
                break
            total[0] += len(chunk)
            output.extend(chunk)
            del output[:-output_limit]

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        import psutil
        try:
            children = psutil.Process(process.pid).children(recursive=True)
            for child in reversed(children):
                try:
                    child.kill()
                except psutil.Error:
                    pass
        except psutil.Error:
            pass
        process.kill()
        process.wait(timeout=5)
    finally:
        reader.join(timeout=3)
    if timed_out:
        raise TimeoutError("Pinned project script timed out; process tree terminated.")
    return {"script": script, "exit_code": process.returncode,
            "stdout": bytes(output).decode("utf-8", errors="replace"), "stderr": "",
            "truncated": total[0] > output_limit}
