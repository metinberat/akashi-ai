import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    app_name: str = "Akashi AI / ABSOLUTE Engine"
    app_version: str = "0.3.0"

    ai_provider: str = "ollama"

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"
    ollama_timeout_seconds: float = 180.0

    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-2.5-flash"

    memory_file: Path = BACKEND_DIR / "data" / "memory.json"
    memory_history_limit: int = 20


@lru_cache
def get_settings() -> Settings:
    memory_path = Path(
        os.getenv(
            "MEMORY_FILE",
            str(BACKEND_DIR / "data" / "memory.json"),
        )
    )

    if not memory_path.is_absolute():
        memory_path = BACKEND_DIR / memory_path

    return Settings(
        app_name=os.getenv(
            "APP_NAME",
            "Akashi AI / ABSOLUTE Engine",
        ),
        app_version=os.getenv("APP_VERSION", "0.3.0"),
        ai_provider=os.getenv(
            "AI_PROVIDER",
            "ollama",
        ).strip().lower(),
        ollama_base_url=os.getenv(
            "OLLAMA_BASE_URL",
            "http://127.0.0.1:11434",
        ).strip(),
        ollama_model=os.getenv(
            "OLLAMA_MODEL",
            "qwen3:8b",
        ).strip(),
        ollama_timeout_seconds=float(
            os.getenv("OLLAMA_TIMEOUT_SECONDS", "180")
        ),
        gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
        gemini_model=os.getenv(
            "GEMINI_MODEL",
            "gemini-2.5-flash",
        ),
        memory_file=memory_path,
        memory_history_limit=int(
            os.getenv("MEMORY_HISTORY_LIMIT", "20")
        ),
    )
