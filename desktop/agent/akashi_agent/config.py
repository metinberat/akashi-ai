import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple


def _default_roots() -> Tuple[Path, ...]:
    home = Path.home()
    cloud_roots = [
        Path(value).expanduser()
        for key in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")
        if (value := os.getenv(key))
    ]
    candidates = [home / "Desktop", home / "Documents"]
    for root in cloud_roots:
        candidates.extend((root / "Desktop", root / "Documents"))
    unique = []
    for candidate in candidates:
        if candidate.exists():
            resolved = candidate.resolve()
            if resolved not in unique:
                unique.append(resolved)
    return tuple(unique)


@dataclass(frozen=True)
class AgentSettings:
    token: Optional[str]
    allowed_roots: Tuple[Path, ...]
    capture_dir: Path
    credential_file: Path
    action_timeout_seconds: int = 120
    max_output_chars: int = 100_000
    script_registry: Optional[Path] = None
    browser_debug_port: int = 9222
    browser_profile_dir: Optional[Path] = None

    @classmethod
    def from_env(cls) -> "AgentSettings":
        configured_roots = [
            Path(item.strip()).expanduser().resolve()
            for item in os.getenv("AKASHI_AGENT_ALLOWED_ROOTS", "").split(";")
            if item.strip()
        ]
        local_data = Path(os.getenv("LOCALAPPDATA", str(Path.home() / ".local"))) / "AkashiAI"
        capture_dir = Path(
            os.getenv("AKASHI_AGENT_CAPTURE_DIR", str(local_data / "captures"))
        ).expanduser().resolve()
        credential_file = Path(
            os.getenv("AKASHI_AGENT_CREDENTIAL_FILE", str(local_data / "device.credential"))
        ).expanduser().resolve()
        browser_profile_dir = Path(
            os.getenv("AKASHI_BROWSER_PROFILE_DIR", str(local_data / "browser-profile"))
        ).expanduser().resolve()
        return cls(
            token=(os.getenv("AKASHI_AGENT_TOKEN") or "").strip() or None,
            allowed_roots=tuple(configured_roots) or _default_roots(),
            capture_dir=capture_dir,
            credential_file=credential_file,
            action_timeout_seconds=max(5, min(int(os.getenv("AKASHI_AGENT_TIMEOUT", "120")), 600)),
            max_output_chars=max(1_000, min(int(os.getenv("AKASHI_AGENT_MAX_OUTPUT", "100000")), 500_000)),
            script_registry=Path(os.environ["AKASHI_AGENT_SCRIPT_REGISTRY"]).resolve() if os.getenv("AKASHI_AGENT_SCRIPT_REGISTRY") else None,
            browser_debug_port=max(1024, min(int(os.getenv("AKASHI_BROWSER_DEBUG_PORT", "9222")), 65535)),
            browser_profile_dir=browser_profile_dir,
        )
