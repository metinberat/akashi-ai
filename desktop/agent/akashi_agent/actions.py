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

from akashi_agent.config import AgentSettings
from akashi_agent.security import PathPolicy
from akashi_agent.scripts import run_pinned_script

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
}
CONFIRM_ACTIONS = {
    "launch_application",
    "open_project",
    "reveal_file",
    "run_project_script",
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
            "reveal_file": {"path"}, "take_screenshot": set(),
            "capture_camera_frame": {"device_index"},
            "run_project_script": {"project", "script", "timeout_seconds"},
        }[name]
        if not isinstance(arguments, dict) or set(arguments) - allowed:
            raise ValueError("Unexpected action arguments.")
        for key, value in arguments.items():
            if key in {"limit", "timeout_seconds", "device_index"}:
                if type(value) is not int:
                    raise ValueError(f"{key} must be an integer.")
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
            if name not in {"edge", "chrome"} or parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
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
        image = ImageGrab.grab(all_screens=True)
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


def _number(value: str) -> Optional[float]:
    try:
        return float(value)
    except ValueError:
        return None
