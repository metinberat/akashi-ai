import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple


def _default_roots() -> Tuple[Path, ...]:
    home = Path.home()
    candidates = (home / "Desktop", home / "Documents")
    return tuple(path.resolve() for path in candidates if path.exists())


@dataclass(frozen=True)
class AgentSettings:
    token: Optional[str]
    allowed_roots: Tuple[Path, ...]
    capture_dir: Path
    credential_file: Path
    action_timeout_seconds: int = 120
    max_output_chars: int = 100_000
    script_registry: Optional[Path] = None

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
        return cls(
            token=(os.getenv("AKASHI_AGENT_TOKEN") or "").strip() or None,
            allowed_roots=tuple(configured_roots) or _default_roots(),
            capture_dir=capture_dir,
            credential_file=credential_file,
            action_timeout_seconds=max(5, min(int(os.getenv("AKASHI_AGENT_TIMEOUT", "120")), 600)),
            max_output_chars=max(1_000, min(int(os.getenv("AKASHI_AGENT_MAX_OUTPUT", "100000")), 500_000)),
            script_registry=Path(os.environ["AKASHI_AGENT_SCRIPT_REGISTRY"]).resolve() if os.getenv("AKASHI_AGENT_SCRIPT_REGISTRY") else None,
        )
