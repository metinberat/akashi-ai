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
    app_version: str = "0.2.0"
    ai_provider: str = "mock"
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-1.5-flash"
    memory_file: Path = BACKEND_DIR / "data" / "memory.json"
    memory_history_limit: int = 20


@lru_cache
def get_settings() -> Settings:
    memory_path = Path(
        os.getenv("MEMORY_FILE", str(BACKEND_DIR / "data" / "memory.json"))
    )
    if not memory_path.is_absolute():
        memory_path = BACKEND_DIR / memory_path

    return Settings(
        app_name=os.getenv("APP_NAME", "Akashi AI / ABSOLUTE Engine"),
        app_version=os.getenv("APP_VERSION", "0.2.0"),
        ai_provider=os.getenv("AI_PROVIDER", "mock").strip().lower(),
        gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-1.5-flash"),
        memory_file=memory_path,
        memory_history_limit=int(os.getenv("MEMORY_HISTORY_LIMIT", "20")),
    )
