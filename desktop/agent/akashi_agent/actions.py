import base64
import io
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from akashi_agent.browser import BrowserAutomationError, ChromiumController
from akashi_agent.config import AgentSettings
from akashi_agent.security import PathPolicy
from akashi_agent.scripts import run_pinned_script
from akashi_agent.windows import computer_input, control_window, list_windows
from akashi_agent.character_patch import stage_patch

SAFE_ACTIONS = {
    "get_system_status",
    "list_processes",
    "application_status",
    "list_directory",
    "find_file",
    "file_metadata",
    # One-shot capture is safe only because execution requires an explicit
    # natural-language request and the agent never records continuously.
    "take_screenshot",
    "capture_camera_frame",
    "get_desktop_state",
    "read_text_file",
    "inspect_git",
    "browser_status",
    "browser_tabs",
    "browser_snapshot",
}
CONFIRM_ACTIONS = {
    "launch_application",
    "open_project",
    "reveal_file",
    "run_project_script",
    "window_control",
    "computer_input",
    "file_operation",
    "browser_start",
    "browser_action",
    "blender_operation",
}


def action_risk(name: str) -> str:
    if name in SAFE_ACTIONS:
        return "safe"
    if name in CONFIRM_ACTIONS:
        return "confirm"
    raise ValueError("Unsupported or restricted local action.")


class ActionExecutor:
    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings
        self.paths = PathPolicy(settings.allowed_roots)
        self._camera_lock = threading.Lock()
        self._character_patch_lock = threading.Lock()
        self.apps = self._discover_apps()
        self._handlers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
            "get_system_status": self._system_status,
            "list_processes": self._list_processes,
            "application_status": self._application_status,
            "list_directory": self._list_directory,
            "find_file": self._find_file,
            "file_metadata": self._file_metadata,
            "launch_application": self._launch_application,
            "open_project": self._open_project,
            "reveal_file": self._reveal_file,
            "take_screenshot": self._take_screenshot,
            "capture_camera_frame": self._capture_camera_frame,
            "run_project_script": self._run_project_script,
            "get_desktop_state": self._get_desktop_state,
            "window_control": self._window_control,
            "computer_input": self._computer_input,
            "read_text_file": self._read_text_file,
            "file_operation": self._file_operation,
            "inspect_git": self._inspect_git,
            "browser_status": self._browser_status,
            "browser_tabs": self._browser_tabs,
            "browser_snapshot": self._browser_snapshot,
            "browser_start": self._browser_start,
            "browser_action": self._browser_action,
            "blender_operation": self._blender_operation,
        }

    @staticmethod
    def _first_existing(candidates: List[Optional[str]]) -> Optional[str]:
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return str(Path(candidate).resolve())
        return None

    def _discover_apps(self) -> Dict[str, str]:
        local = Path(os.getenv("LOCALAPPDATA", ""))
        program_files = Path(os.getenv("ProgramFiles", "C:/Program Files"))
        program_x86 = Path(os.getenv("ProgramFiles(x86)", "C:/Program Files (x86)"))
        candidates = {
            "vscode": [
                str(local / "Programs/Microsoft VS Code/Code.exe"),
                str(program_files / "Microsoft VS Code/Code.exe"),
            ],
            "edge": [
                str(program_x86 / "Microsoft/Edge/Application/msedge.exe"),
                str(program_files / "Microsoft/Edge/Application/msedge.exe"),
            ],
            "chrome": [
                str(program_files / "Google/Chrome/Application/chrome.exe"),
                str(program_x86 / "Google/Chrome/Application/chrome.exe"),
            ],
            "terminal": [
                str(local / "Microsoft/WindowsApps/wt.exe"),
                shutil.which("powershell.exe"),
            ],
            "spotify": [str(os.getenv("APPDATA", "")) + "/Spotify/Spotify.exe"],
            "discord": [
                str(path)
                for path in sorted(local.glob("Discord/app-*/Discord.exe"), reverse=True)
            ],
            "notepad": [str(Path(os.getenv("WINDIR", "C:/Windows")) / "System32/notepad.exe")],
            "explorer": [str(Path(os.getenv("WINDIR", "C:/Windows")) / "explorer.exe")],
            "blender": [
                str(path)
                for path in sorted(program_files.glob("Blender Foundation/Blender */blender.exe"), reverse=True)
            ],
        }
        discovered = {
            name: path
            for name, values in candidates.items()
            if (path := self._first_existing(values)) is not None
        }
        if "chrome" in discovered:
            discovered["browser"] = discovered["chrome"]
        elif "edge" in discovered:
            discovered["browser"] = discovered["edge"]
        return discovered

    def capabilities(self) -> List[str]:
        return sorted(name for name in self._handlers if name != "run_project_script" or self.settings.script_registry)

    def execute(self, name: str, arguments: Dict[str, Any], approved: bool = False) -> Dict[str, Any]:
        risk = action_risk(name)
        allowed = {
            "get_system_status": set(), "list_processes": {"limit"},
            "application_status": {"application"}, "list_directory": {"path", "limit"},
            "find_file": {"root", "query", "limit"}, "file_metadata": {"path"},
            "launch_application": {"application", "url"}, "open_project": {"path"},
            "reveal_file": {"path"}, "take_screenshot": {"window_id"},
            "capture_camera_frame": {"device_index"},
            "run_project_script": {"project", "script", "timeout_seconds"},
            "get_desktop_state": {"limit"},
            "window_control": {"operation", "window_id", "title", "x", "y", "width", "height"},
            "computer_input": {"operation", "x", "y", "x2", "y2", "steps", "button", "delta", "horizontal", "text", "keys"},
            "read_text_file": {"path", "max_chars"},
            "file_operation": {"operation", "source", "destination", "content", "overwrite"},
            "inspect_git": {"project", "operation", "revision", "path", "limit"},
            "browser_status": set(),
            "browser_tabs": set(),
            "browser_snapshot": {"tab_id"},
            "browser_start": {"url"},
            "browser_action": {"operation", "tab_id", "url", "target", "value", "delta", "accept"},
            "blender_operation": {"operation", "project", "output", "patch", "timeout_seconds", "chunk", "chunk_index", "chunk_count", "sha256", "offset", "length", "view", "frame"},
        }[name]
        if not isinstance(arguments, dict) or set(arguments) - allowed:
            raise ValueError("Unexpected action arguments.")
        for key, value in arguments.items():
            if key in {"limit", "timeout_seconds", "device_index", "window_id", "x", "y", "x2", "y2", "width", "height", "steps", "delta", "max_chars", "chunk_index", "chunk_count", "offset", "length", "frame"}:
                if type(value) is not int:
                    raise ValueError(f"{key} must be an integer.")
            elif key in {"horizontal", "overwrite"}:
                if type(value) is not bool:
                    raise ValueError(f"{key} must be a boolean.")
            elif key == "target":
                if not isinstance(value, dict) or set(value) - {"selector", "text", "role", "label", "aria_label", "placeholder", "index"}:
                    raise ValueError("target must be a bounded semantic locator.")
                for target_key, target_value in value.items():
                    if target_key == "index":
                        if type(target_value) is not int or target_value < 0 or target_value > 239:
                            raise ValueError("target index must be between 0 and 239.")
                    elif not isinstance(target_value, str) or len(target_value) > 500:
                        raise ValueError("target locator values must be bounded strings.")
            elif key == "accept":
                if type(value) is not bool:
                    raise ValueError("accept must be a boolean.")
            elif key == "keys":
                if not (
                    isinstance(value, str)
                    or isinstance(value, list)
                    and len(value) <= 5
                    and all(isinstance(item, str) and len(item) <= 32 for item in value)
                ):
                    raise ValueError("keys must be a bounded string or list.")
            elif key == "content":
                if not isinstance(value, str) or len(value) > 100_000:
                    raise ValueError("content must be a bounded string.")
            elif key == "chunk":
                if not isinstance(value, str) or len(value.encode("utf-8")) > 24000:
                    raise ValueError("chunk exceeds the character patch transport budget.")
            elif not isinstance(value, str) or len(value) > 4096:
                raise ValueError(f"{key} must be a bounded string.")
        if risk == "confirm" and not approved:
            raise PermissionError("This local action requires explicit approval.")
        handler = self._handlers[name]
        started = time.monotonic()
        data = handler(dict(arguments))
        return {
            "action": name,
            "risk": risk,
            "ok": True,
            "duration_ms": round((time.monotonic() - started) * 1000),
            "data": data,
        }

    def _browser(self) -> ChromiumController:
        executable = self.apps.get("chrome") or self.apps.get("edge") or self.apps.get("browser")
        profile = self.settings.browser_profile_dir
        if not executable or profile is None:
            raise RuntimeError("No supported Chromium browser was discovered.")
        return ChromiumController(executable, self.settings.browser_debug_port, profile)

    def _browser_status(self, _arguments: Dict[str, Any]) -> Dict[str, Any]:
        return self._browser().status()

    def _browser_tabs(self, _arguments: Dict[str, Any]) -> Dict[str, Any]:
        return {"tabs": self._browser().tabs()}

    def _browser_snapshot(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return self._browser().snapshot(str(arguments.get("tab_id") or "") or None)

    def _browser_start(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        url = self._validated_browser_url(str(arguments.get("url") or "about:blank"), allow_blank=True)
        return self._browser().start(url)

    def _browser_action(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        operation = str(arguments.get("operation") or "").strip().casefold()
        supported = {
            "new_tab", "close_tab", "switch_tab", "navigate", "back", "forward", "reload",
            "click", "type", "clear", "select", "check", "uncheck", "scroll", "handle_dialog",
        }
        if operation not in supported:
            raise ValueError("Unsupported browser operation.")
        clean = dict(arguments)
        clean["operation"] = operation
        if operation in {"navigate", "new_tab"}:
            clean["url"] = self._validated_browser_url(str(arguments.get("url") or ""), allow_blank=operation == "new_tab")
        if operation in {"click", "type", "clear", "select", "check", "uncheck"} and not arguments.get("target"):
            raise ValueError("Semantic browser actions require a target locator.")
        try:
            return self._browser().action(operation, clean)
        except BrowserAutomationError as exc:
            raise RuntimeError(str(exc)) from exc

    def _blender_operation(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        operation = str(arguments.get("operation") or "").strip().casefold()
        if set(arguments) & {"view", "frame"} and operation != "render_production":
            raise ValueError("Only production renders accept a bounded view/frame.")
        if operation == "inspect_production_export":
            if set(arguments)-{"operation","project"}: raise ValueError("Unexpected export inspection arguments.")
            from .production_export import inspect_export
            return inspect_export(self.paths, arguments)
        if operation == "read_character_chunk":
            if set(arguments)-{"operation", "project", "offset", "length"}:
                raise ValueError("Unexpected canonical readback arguments.")
            from .character_document import read_chunk
            return read_chunk(self.paths, arguments)
        if operation in {"stage_weights", "stage_character", "stage_production"}:
            if set(arguments)-{"operation", "output", "chunk", "chunk_index", "chunk_count", "sha256"}:
                raise ValueError("Unexpected character staging arguments.")
            with self._character_patch_lock:
                return stage_patch(self.paths, arguments, "production" if operation == "stage_production" else "character" if operation == "stage_character" else "weights")
        if set(arguments) & {"offset", "length"}:
            raise ValueError("Only canonical readback accepts offsets.")
        if set(arguments) & {"chunk", "chunk_index", "chunk_count", "sha256"}:
            raise ValueError("Only stage_weights accepts chunk data.")
        executable = self.apps.get("blender")
        if not executable:
            raise RuntimeError("Blender was not discovered.")
        if operation not in {"inspect_scene", "inspect_character", "render_current", "render_production", "export_gltf", "apply_weights", "verify_weights", "test_deformation", "build_character", "build_production", "present_production", "verify_production"}:
            raise ValueError("Unsupported Blender operation.")
        project = self.paths.resolve(str(arguments.get("project") or ""))
        if not project.is_file() or project.suffix.casefold() != (".json" if operation in {"build_character","build_production"} else ".blend"):
            raise ValueError("Blender project must be an existing .blend file inside an approved root.")
        if operation in {"build_character","build_production"}:
            from .character_document import validate_document
            if project.stat().st_size > 32*1024*1024:
                raise ValueError("Character construction input exceeds budget.")
            validate_document(json.loads(project.read_text(encoding="utf-8")), construction=True)
            if operation=="build_production":
                from .production_contract import validate_production
                validate_production(json.loads(project.read_text(encoding="utf-8")))
        command = [executable, "--disable-autoexec", "--background"] + (["--factory-startup"] if operation in {"build_character","build_production"} else [str(project)])
        command += ["--python", str(Path(__file__).with_name("blender_bridge.py")), "--", "--operation", operation]
        if operation == "render_production":
            view, frame = arguments.get("view", "ThreeQuarter"), arguments.get("frame", 1)
            if view not in {"Front", "ThreeQuarter", "Back"} or not 1 <= frame <= 192:
                raise ValueError("Unsupported production camera/frame.")
            command.extend(("--view", view, "--frame", str(frame)))
        if operation in {"build_character","build_production"}:
            command.extend(("--character", str(project)))
        output: Optional[Path] = None
        if operation != "inspect_scene":
            output = self.paths.resolve(str(arguments.get("output") or ""), must_exist=False)
            self.paths.resolve(str(output.parent))
            allowed = {".json"} if operation in {"inspect_character", "test_deformation", "verify_weights", "verify_production"} else {".blend"} if operation in {"apply_weights", "build_character", "build_production", "present_production"} else {".png", ".jpg", ".jpeg"} if operation in {"render_current", "render_production"} else {".gltf", ".glb"}
            if output.suffix.casefold() not in allowed:
                raise ValueError("Blender output extension does not match the requested operation.")
            if output.exists():
                raise ValueError("Blender output already exists; choose a new artifact path.")
            command.extend(("--output", str(output)))
        if operation in {"apply_weights", "verify_weights", "present_production"}:
            patch = self.paths.resolve(str(arguments.get("patch") or ""))
            if patch.suffix.casefold() != ".json" or not patch.is_file() or patch.stat().st_size > 32*1024*1024:
                raise ValueError("Weight patch must be bounded JSON inside an approved root.")
            command.extend(("--patch", str(patch)))
            if operation=="present_production":
                from .production_contract import validate_production
                validate_production(json.loads(patch.read_text(encoding="utf-8")))
        elif arguments.get("patch"):
            raise ValueError("Only apply_weights/verify_weights accept a patch.")
        timeout = max(10, min(int(arguments.get("timeout_seconds", self.settings.action_timeout_seconds)), 300))
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False, shell=False,
            env={key: os.environ[key] for key in ("SystemRoot", "WINDIR", "PATH", "PATHEXT", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA", "APPDATA") if key in os.environ},
        )
        marker = "AKASHI_BLENDER_RESULT="
        line = next((item for item in reversed(completed.stdout.splitlines()) if item.startswith(marker)), "")
        if completed.returncode != 0 or not line:
            detail = (completed.stderr or completed.stdout)[-1000:]
            raise RuntimeError(f"Blender adapter failed: {detail}")
        result = json.loads(line[len(marker):])
        if not isinstance(result, dict) or not result.get("verified"):
            raise RuntimeError("Blender operation did not produce verified output.")
        if output is not None and (not output.is_file() or output.stat().st_size <= 0):
            raise RuntimeError("Blender reported success but the output artifact is missing.")
        return result

    @staticmethod
    def _validated_browser_url(value: str, allow_blank: bool = False) -> str:
        url = value.strip()
        if allow_blank and url == "about:blank":
            return url
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("Browser navigation accepts only credential-free HTTP(S) URLs.")
        return url

    def _system_status(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        try:
            import psutil
        except ImportError as exc:
            raise RuntimeError("System telemetry requires the psutil dependency.") from exc
        root = Path.home().anchor or "C:/"
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(root)
        network_online = any(
            stats.isup and name.casefold() != "loopback"
            for name, stats in psutil.net_if_stats().items()
        )
        result: Dict[str, Any] = {
            "hostname": socket.gethostname(),
            "os": platform.platform(),
            "cpu": {
                "name": platform.processor() or "unknown",
                "logical_cores": psutil.cpu_count(logical=True),
                "usage_percent": psutil.cpu_percent(interval=0.15),
            },
            "memory": {
                "total_bytes": memory.total,
                "available_bytes": memory.available,
                "usage_percent": memory.percent,
            },
            "disk": {
                "root": root,
                "total_bytes": disk.total,
                "free_bytes": disk.free,
                "usage_percent": disk.percent,
            },
            "uptime_seconds": max(0, int(time.time() - psutil.boot_time())),
            "network_online": network_online,
            "gpu": self._gpu_status(),
        }
        return result

    @staticmethod
    def _gpu_status() -> Dict[str, Any]:
        executable = shutil.which("nvidia-smi")
        if not executable:
            return {"available": False, "reason": "nvidia-smi not available"}
        command = [
            executable,
            "--query-gpu=name,utilization.gpu,temperature.gpu,memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return {"available": False, "reason": "GPU query failed"}
        if completed.returncode != 0 or not completed.stdout.strip():
            return {"available": False, "reason": "GPU telemetry unavailable"}
        devices = []
        for line in completed.stdout.splitlines():
            parts = [item.strip() for item in line.split(",")]
            if len(parts) == 5:
                devices.append(
                    {
                        "name": parts[0],
                        "usage_percent": _number(parts[1]),
                        "temperature_c": _number(parts[2]),
                        "memory_used_mb": _number(parts[3]),
                        "memory_total_mb": _number(parts[4]),
                    }
                )
        return {"available": bool(devices), "devices": devices}

    def _list_processes(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        try:
            import psutil
        except ImportError as exc:
            raise RuntimeError("Process listing requires the psutil dependency.") from exc
        limit = max(1, min(int(arguments.get("limit", 50)), 200))
        processes = []
        for process in psutil.process_iter(["pid", "name", "status", "memory_percent"]):
            try:
                info = process.info
                processes.append(
                    {
                        "pid": info["pid"],
                        "name": info.get("name") or "unknown",
                        "status": info.get("status") or "unknown",
                        "memory_percent": round(float(info.get("memory_percent") or 0), 2),
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        processes.sort(key=lambda item: item["memory_percent"], reverse=True)
        return {"processes": processes[:limit]}

    def _application_status(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        name = str(arguments.get("application") or "").strip().casefold()
        if name not in self.apps:
            raise ValueError("Application is not in the discovered allowlist.")
        process_result = self._list_processes({"limit": 200})["processes"]
        executable_name = Path(self.apps[name]).name.casefold()
        matches = [item for item in process_result if item["name"].casefold() == executable_name]
        return {"application": name, "running": bool(matches), "processes": matches}

    def _list_directory(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        path = self.paths.resolve(str(arguments.get("path") or ""))
        if not path.is_dir():
            raise ValueError("Path is not a directory.")
        limit = max(1, min(int(arguments.get("limit", 100)), 500))
        entries = []
        for item in path.iterdir():
            try:
                item = self.paths.resolve(str(item))
                stat = item.stat()
                entries.append(
                    {
                        "name": item.name,
                        "path": str(item),
                        "is_directory": item.is_dir(),
                        "size": stat.st_size,
                        "modified_at": stat.st_mtime,
                    }
                )
                if len(entries) >= limit:
                    break
            except (OSError, ValueError):
                continue
        return {"path": str(path), "entries": entries}

    def _find_file(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        root = self.paths.resolve(str(arguments.get("root") or ""))
        if not root.is_dir():
            raise ValueError("Search root is not a directory.")
        query = str(arguments.get("query") or "").strip().casefold()
        if not query or len(query) > 200 or any(char in query for char in "*/?[]"):
            raise ValueError("Use a plain filename fragment without wildcard syntax.")
        limit = max(1, min(int(arguments.get("limit", 25)), 100))
        matches = []
        visited = 0
        deadline = time.monotonic() + 5
        for directory, dirs, files in os.walk(root, followlinks=False):
            safe_dirs = []
            for child in dirs:
                candidate = Path(directory) / child
                try:
                    resolved = self.paths.resolve(str(candidate))
                    if resolved == candidate.absolute() and not candidate.is_symlink() and not (hasattr(candidate, "is_junction") and candidate.is_junction()):
                        safe_dirs.append(child)
                except (OSError, ValueError):
                    continue
            dirs[:] = safe_dirs
            for name in safe_dirs + files:
                visited += 1
                if visited > 10_000 or time.monotonic() > deadline or len(matches) >= limit:
                    return {"root": str(root), "query": query, "matches": matches, "truncated": True}
                try:
                    item = self.paths.resolve(str(Path(directory) / name))
                except (OSError, ValueError):
                    continue
                if query in item.name.casefold():
                    matches.append({"name": item.name, "path": str(item), "is_directory": item.is_dir()})
        return {"root": str(root), "query": query, "matches": matches, "truncated": False}

    def _file_metadata(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        path = self.paths.resolve(str(arguments.get("path") or ""))
        stat = path.stat()
        return {
            "name": path.name,
            "path": str(path),
            "is_directory": path.is_dir(),
            "size": stat.st_size,
            "created_at": stat.st_ctime,
            "modified_at": stat.st_mtime,
            "suffix": path.suffix.casefold(),
        }

    def _launch_application(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        name = str(arguments.get("application") or "").strip().casefold()
        executable = self.apps.get(name)
        if executable is None:
            raise ValueError("Application is not in the discovered allowlist.")
        command = [executable]
        target = str(arguments.get("url") or "").strip()
        if target:
            parsed = urlparse(target)
            if name not in {"edge", "chrome", "browser"} or parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
                raise ValueError("Only HTTP(S) URLs may be passed to an allowlisted browser.")
            command.append(target)
        process = subprocess.Popen(
            command,
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        confirmed = self._confirm_process(Path(executable).name, process)
        if not confirmed:
            raise RuntimeError("Application launch could not be confirmed.")
        return {"application": name, "pid": process.pid, "confirmed": True}

    def _open_project(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        path = self.paths.resolve(str(arguments.get("path") or ""))
        if not path.is_dir():
            raise ValueError("Project path is not a directory.")
        executable = self.apps.get("vscode")
        if executable is None:
            raise RuntimeError("VS Code was not found in the application allowlist.")
        process = subprocess.Popen(
            [executable, str(path)],
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        confirmed = self._confirm_process(Path(executable).name, process)
        if not confirmed:
            raise RuntimeError("Project launch could not be confirmed.")
        return {
            "application": "vscode",
            "path": str(path),
            "pid": process.pid,
            "confirmed": True,
        }

    @staticmethod
    def _confirm_process(executable_name: str, process: subprocess.Popen[Any]) -> bool:
        """Reject immediate failures and confirm a matching process exists."""
        try:
            import psutil
        except ImportError as exc:
            raise RuntimeError("Application confirmation requires psutil.") from exc
        target = executable_name.casefold()
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            return_code = process.poll()
            if return_code not in {None, 0}:
                return False
            for candidate in psutil.process_iter(["name"]):
                try:
                    if str(candidate.info.get("name") or "").casefold() == target:
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            time.sleep(0.1)
        return False

    def _reveal_file(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        path = self.paths.resolve(str(arguments.get("path") or ""))
        explorer = Path(os.environ.get("WINDIR", "C:/Windows")) / "explorer.exe"
        if path.is_dir():
            command = [str(explorer), str(path)]
        else:
            command = [str(explorer), f"/select,{path}"]
        process = subprocess.Popen(
            command,
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {"path": str(path), "pid": process.pid}

    def _take_screenshot(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from PIL import ImageGrab
        except ImportError as exc:
            raise RuntimeError("Screenshots require the Pillow dependency.") from exc
        window_id = arguments.get("window_id")
        source_window = None
        if window_id is not None:
            state = list_windows(200)
            source_window = next(
                (item for item in state["windows"] if item["window_id"] == int(window_id)),
                None,
            )
            if source_window is None:
                raise ValueError("Screenshot window is no longer available.")
            bounds = source_window["bounds"]
            bbox = (
                bounds["x"], bounds["y"],
                bounds["x"] + bounds["width"], bounds["y"] + bounds["height"],
            )
            image = ImageGrab.grab(bbox=bbox, all_screens=True)
            virtual_screen = {
                "x": bounds["x"], "y": bounds["y"],
                "width": bounds["width"], "height": bounds["height"],
            }
        else:
            image = ImageGrab.grab(all_screens=True)
            virtual_screen = list_windows(1)["virtual_screen"]
        original_width, original_height = image.width, image.height
        if image.width > 1600:
            height = round(image.height * (1600 / image.width))
            image.thumbnail((1600, height))
        output = io.BytesIO()
        image.convert("RGB").save(output, format="JPEG", quality=72, optimize=True)
        content = output.getvalue()
        if len(content) > 1_500_000:
            raise RuntimeError("Screenshot remains too large after safe compression.")
        return {
            "media_type": "image/jpeg",
            "width": image.width,
            "height": image.height,
            "original_width": original_width,
            "original_height": original_height,
            "virtual_screen": virtual_screen,
            "source_window": {
                "window_id": source_window["window_id"],
                "title": source_window["title"],
                "process_name": source_window["process_name"],
            } if source_window else None,
            "base64": base64.b64encode(content).decode("ascii"),
        }

    def _capture_camera_frame(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError(
                "Camera capture requires the opencv-python-headless dependency."
            ) from exc
        device_index = int(arguments.get("device_index", 0))
        if device_index < 0 or device_index > 8:
            raise ValueError("Camera device_index must be between 0 and 8.")
        if not self._camera_lock.acquire(blocking=False):
            raise RuntimeError("Camera is already processing another capture.")
        backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
        try:
            indexes = [device_index] + [index for index in range(6) if index != device_index]
            camera = None
            frame = None
            active_index = device_index
            for candidate_index in indexes:
                candidate_camera = cv2.VideoCapture(candidate_index, backend)
                if not candidate_camera.isOpened():
                    candidate_camera.release()
                    continue
                candidate_camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                candidate_camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                deadline = time.monotonic() + 2.0
                candidate_frame = None
                while time.monotonic() < deadline:
                    ok, image = candidate_camera.read()
                    if ok and image is not None and image.size:
                        candidate_frame = image
                        for _ in range(3):
                            ok, image = candidate_camera.read()
                            if ok and image is not None and image.size:
                                candidate_frame = image
                        break
                if candidate_frame is not None:
                    camera = candidate_camera
                    frame = candidate_frame
                    active_index = candidate_index
                    break
                candidate_camera.release()
            if camera is None or frame is None:
                raise RuntimeError("No camera is available.")
            try:
                height, width = frame.shape[:2]
                if width > 1600:
                    scale = 1600 / width
                    frame = cv2.resize(
                        frame,
                        (1600, max(1, round(height * scale))),
                        interpolation=cv2.INTER_AREA,
                    )
                    height, width = frame.shape[:2]
                encoded_ok, encoded = cv2.imencode(
                    ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 78]
                )
                if not encoded_ok:
                    raise RuntimeError("Camera frame encoding failed.")
                content = encoded.tobytes()
                if len(content) > 1_500_000:
                    raise RuntimeError("Camera frame exceeded the safe size limit.")
                return {
                    "media_type": "image/jpeg",
                    "source": "camera",
                    "device_index": active_index,
                    "width": width,
                    "height": height,
                    "base64": base64.b64encode(content).decode("ascii"),
                }
            finally:
                camera.release()
        finally:
            self._camera_lock.release()

    def _run_project_script(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if not self.settings.script_registry:
            raise PermissionError("Project scripts are disabled. Configure a local pinned script registry first.")
        project = self.paths.resolve(str(arguments.get("project") or ""))
        if not project.is_dir():
            raise ValueError("Project path is not a directory.")
        script = str(arguments.get("script") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9:_-]{1,80}", script):
            raise ValueError("Invalid npm script name.")
        package_file = self.paths.resolve(str(project / "package.json"))
        if not package_file.is_file():
            raise ValueError("The selected project has no package.json.")
        package = json.loads(package_file.read_text(encoding="utf-8"))
        scripts = package.get("scripts", {})
        if not isinstance(scripts, dict) or script not in scripts:
            raise ValueError("The requested npm script is not declared by this project.")
        timeout = max(1, min(int(arguments.get("timeout_seconds", self.settings.action_timeout_seconds)), 300))
        return run_pinned_script(project, package_file, script, self.settings.script_registry, timeout, self.settings.max_output_chars)

    def _get_desktop_state(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return list_windows(max(1, min(int(arguments.get("limit", 100)), 200)))

    @staticmethod
    def _window_control(arguments: Dict[str, Any]) -> Dict[str, Any]:
        return control_window(arguments)

    @staticmethod
    def _computer_input(arguments: Dict[str, Any]) -> Dict[str, Any]:
        return computer_input(arguments)

    def _read_text_file(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        path = self.paths.resolve(str(arguments.get("path") or ""))
        if not path.is_file():
            raise ValueError("Path is not a file.")
        max_chars = max(1, min(int(arguments.get("max_chars", 40_000)), 100_000))
        if path.stat().st_size > 2_000_000:
            raise ValueError("File is too large for bounded text reading.")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("File is not UTF-8 text.") from exc
        return {
            "path": str(path),
            "content": text[:max_chars],
            "truncated": len(text) > max_chars,
        }

    def _file_operation(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        operation = str(arguments.get("operation") or "").strip().casefold()
        overwrite = bool(arguments.get("overwrite", False))
        if operation == "create_text":
            destination = self.paths.resolve(
                str(arguments.get("destination") or ""), must_exist=False
            )
            self.paths.resolve(str(destination.parent))
            if destination.exists() and not overwrite:
                raise FileExistsError("Destination already exists; overwrite was not approved.")
            content = str(arguments.get("content") or "")
            if len(content) > 100_000:
                raise ValueError("Text content exceeds the 100000 character limit.")
            temporary = destination.with_name(f".{destination.name}.akashi-tmp")
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(destination)
            return {
                "operation": operation,
                "destination": str(destination),
                "verified": destination.is_file(),
            }

        source = self.paths.resolve(str(arguments.get("source") or ""))
        destination = self.paths.resolve(
            str(arguments.get("destination") or ""), must_exist=False
        )
        self.paths.resolve(str(destination.parent))
        if destination.exists() and not overwrite:
            raise FileExistsError("Destination already exists; overwrite was not approved.")
        if operation == "copy":
            if source.is_dir():
                if destination.exists():
                    raise FileExistsError("Directory destination already exists.")
                self._validate_tree_size(source)
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)
        elif operation in {"move", "rename"}:
            shutil.move(str(source), str(destination))
        else:
            raise ValueError("Unsupported file operation.")
        moved = operation in {"move", "rename"}
        return {
            "operation": operation,
            "source": str(source),
            "destination": str(destination),
            "verified": destination.exists() and (not moved or not source.exists()),
        }

    @staticmethod
    def _validate_tree_size(root: Path) -> None:
        count = 0
        total = 0
        deadline = time.monotonic() + 5
        for directory, dirs, files in os.walk(root, followlinks=False):
            safe_dirs = []
            for name in dirs:
                path = Path(directory) / name
                if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                    continue
                safe_dirs.append(name)
            dirs[:] = safe_dirs
            for name in files:
                path = Path(directory) / name
                if path.is_symlink():
                    raise ValueError("Directory copies cannot contain symbolic links.")
                count += 1
                total += path.stat().st_size
                if count > 5_000 or total > 512 * 1024 * 1024 or time.monotonic() > deadline:
                    raise ValueError("Directory copy exceeds the bounded file, size or scan limit.")

    def _inspect_git(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        project = self.paths.resolve(str(arguments.get("project") or ""))
        if not project.is_dir() or not (project / ".git").exists():
            raise ValueError("Project is not a Git working tree.")
        git = shutil.which("git")
        if not git:
            raise RuntimeError("Git is not installed.")
        operation = str(arguments.get("operation") or "status").strip().casefold()
        limit = max(1, min(int(arguments.get("limit", 20)), 100))
        if operation == "status":
            command = [git, "status", "--short", "--branch"]
        elif operation == "branch":
            command = [git, "branch", "--show-current"]
        elif operation == "log":
            command = [git, "log", "--oneline", "--decorate", "-n", str(limit)]
        elif operation == "show":
            relative = str(arguments.get("path") or "").strip()
            path_arguments: List[str] = []
            if relative:
                candidate = self.paths.resolve(str(project / relative))
                try:
                    relative = str(candidate.relative_to(project))
                except ValueError as exc:
                    raise PermissionError("Git path must stay inside the selected project.") from exc
                path_arguments = ["--", relative]
            revision = str(arguments.get("revision") or "HEAD").strip()
            if revision.startswith("-") or not re.fullmatch(r"[A-Za-z0-9_./^~-]{1,100}", revision):
                raise ValueError("Invalid Git revision.")
            command = [git, "show", "--stat", "--no-patch", "--oneline", "--no-ext-diff", revision, *path_arguments]
        else:
            raise ValueError("Unsupported Git inspection operation.")
        child_environment = {
            key: os.environ[key]
            for key in ("SystemRoot", "WINDIR", "PATH", "PATHEXT", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA", "APPDATA")
            if key in os.environ
        }
        child_environment["GIT_TERMINAL_PROMPT"] = "0"
        completed = subprocess.run(
            command,
            cwd=project,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
            shell=False,
            env=child_environment,
        )
        output = (completed.stdout + completed.stderr)[: self.settings.max_output_chars]
        return {
            "operation": operation,
            "project": str(project),
            "exit_code": completed.returncode,
            "output": output,
            "truncated": len(completed.stdout) + len(completed.stderr) > self.settings.max_output_chars,
            "verified": completed.returncode == 0,
        }


def _number(value: str) -> Optional[float]:
    try:
        return float(value)
    except ValueError:
        return None
