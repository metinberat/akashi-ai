import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
except ImportError:  # Packaged Desktop Core can run without a repository .env.
    def load_dotenv(_path: Path) -> bool:
        return False

BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    app_name: str = "Akashi AI / ABSOLUTE Engine"
    app_version: str = "0.4.0-pre-astra"

    ai_provider: str = "ollama"

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"
    ollama_timeout_seconds: float = 180.0

    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-2.5-flash"

    comfy_base_url: str = "http://127.0.0.1:8188"
    max_image_upload_bytes: int = 20 * 1024 * 1024

    api_token: Optional[str] = None
    cors_origins: tuple[str, ...] = (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3100",
        "http://127.0.0.1:3100",
        "https://localhost",
        "http://localhost",
        "capacitor://localhost",
        "akashi://app",
    )

    memory_file: Path = BACKEND_DIR / "data" / "memory.json"
    memory_history_limit: int = 20
    memory_summary_max_chars: int = 4_000
    long_term_memory_file: Path = BACKEND_DIR / "data" / "long_term_memory.json"
    task_file: Path = BACKEND_DIR / "data" / "tasks.json"
    upload_dir: Path = BACKEND_DIR / "data" / "uploads"
    file_index_file: Path = BACKEND_DIR / "data" / "file_index.json"
    device_file: Path = BACKEND_DIR / "data" / "devices.json"
    intelligence_file: Path = BACKEND_DIR / "data" / "private" / "intelligence.json"
    schedule_file: Path = BACKEND_DIR / "data" / "private" / "schedules.json"
    live_state_file: Path = BACKEND_DIR / "data" / "private" / "live_interactions.json"
    computer_state_file: Path = BACKEND_DIR / "data" / "private" / "computer_sessions.json"
    autonomy_state_file: Path = BACKEND_DIR / "data" / "private" / "autonomy_tasks.json"
    autonomy_skill_file: Path = BACKEND_DIR / "data" / "private" / "autonomy_skills.json"
    autonomy_knowledge_file: Path = BACKEND_DIR / "data" / "private" / "autonomy_knowledge.json"
    voice_state_file: Path = BACKEND_DIR / "data" / "private" / "voice_sessions.json"
    phone_calls_file: Path = BACKEND_DIR / "data" / "private" / "phone_calls.json"
    max_upload_bytes: int = 10 * 1024 * 1024

    research_provider: str = "duckduckgo"
    wikipedia_language: str = "en"
    searxng_base_url: Optional[str] = None
    research_timeout_seconds: float = 20.0
    miss_minutes_enabled: bool = False
    miss_minutes_timezone: str = "Europe/Istanbul"
    miss_minutes_discovery_minutes: int = 360
    miss_minutes_brief_minutes: int = 1440

    model_fast_provider: str = ""
    model_quality_provider: str = ""
    model_reasoning_provider: str = ""
    model_vision_provider: str = ""
    model_fast_name: str = ""
    model_quality_name: str = ""
    model_reasoning_name: str = ""
    model_vision_name: str = ""

    pairing_code_ttl_seconds: int = 600
    device_online_ttl_seconds: int = 75

    # Server-side bridge to the loopback-only Windows agent. The token is never
    # returned to clients or embedded in frontend bundles.
    local_agent_base_url: str = "http://127.0.0.1:8765"
    local_agent_token: Optional[str] = None
    local_agent_timeout_seconds: float = 150.0
    akashi_project_path: Optional[Path] = None
    computer_max_steps: int = 12
    autonomy_max_subgoals: int = 40
    autonomy_local_fallback: bool = True
    expertise_db: Path = BACKEND_DIR / "data" / "private" / "expertise.sqlite3"
    # Spatial Lab: scene sessions/assets under private data; FORM is read-only.
    spatial_dir: Path = BACKEND_DIR / "data" / "private" / "spatial"
    spatial_form_data_dir: Optional[Path] = None
    spatial_interpreter: str = "auto"
    # None: next to spatial_dir (keeps tests and custom data roots self-contained).
    remote_dir: Optional[Path] = None
    # Provider-independent: any HTTPS origins that reach this Core (LAN reverse
    # proxy, VPN, tunnel). Advertised to paired devices for failover; optional.
    remote_endpoints: tuple[str, ...] = ()

    phone_enabled: bool = False
    outbound_calls_enabled: bool = False
    livekit_url: Optional[str] = None
    livekit_api_key: Optional[str] = None
    livekit_api_secret: Optional[str] = None
    livekit_sip_outbound_trunk_id: Optional[str] = None
    phone_agent_name: str = "akashi-phone"
    phone_worker_token: Optional[str] = None
    phone_core_url: str = "http://127.0.0.1:8000"
    phone_stt_model: str = "cartesia/ink-whisper"
    phone_stt_language: str = "tr"
    phone_tts_model: str = "cartesia/sonic-3"
    phone_tts_voice: Optional[str] = None
    phone_tts_language: str = "tr"
    verimor_sip_server: str = "sip.verimor.com.tr"
    verimor_sip_username: Optional[str] = None
    verimor_sip_password: Optional[str] = None


@lru_cache
def get_settings() -> Settings:
    data_root = Path(os.getenv("AKASHI_DATA_DIR", str(BACKEND_DIR / "data")))
    if not data_root.is_absolute():
        data_root = BACKEND_DIR / data_root

    memory_path = Path(
        os.getenv(
            "MEMORY_FILE",
            str(data_root / "memory.json"),
        )
    )

    if not memory_path.is_absolute():
        memory_path = BACKEND_DIR / memory_path

    def data_path(variable: str, default_name: str) -> Path:
        configured = Path(
            os.getenv(variable, str(data_root / default_name))
        )
        return configured if configured.is_absolute() else BACKEND_DIR / configured

    gemini_key = (os.getenv("GEMINI_API_KEY") or "").strip() or None
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    vision_provider = os.getenv("AKASHI_MODEL_VISION_PROVIDER", "").strip().lower()
    vision_model = os.getenv("AKASHI_MODEL_VISION_NAME", "").strip()
    # A configured Gemini backend is already image-capable. Make that existing
    # capability available to LIVE screen/camera requests unless the operator
    # explicitly chooses a different VISION mapping.
    if gemini_key and not vision_provider and not vision_model:
        vision_provider = "gemini"
        vision_model = gemini_model

    project_value = (os.getenv("AKASHI_PROJECT_PATH") or "").strip()
    project_path = Path(project_value).expanduser().resolve() if project_value else None

    return Settings(
        app_name=os.getenv(
            "APP_NAME",
            "Akashi AI / ABSOLUTE Engine",
        ),
        app_version=os.getenv("APP_VERSION", "0.4.0-pre-astra"),
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
        gemini_api_key=gemini_key,
        gemini_model=gemini_model,
        comfy_base_url=os.getenv(
            "COMFY_BASE_URL", "http://127.0.0.1:8188"
        ).strip().rstrip("/"),
        max_image_upload_bytes=int(
            os.getenv("MAX_IMAGE_UPLOAD_BYTES", str(20 * 1024 * 1024))
        ),
        api_token=(os.getenv("AKASHI_API_TOKEN") or "").strip() or None,
        cors_origins=tuple(
            origin.strip().rstrip("/")
            for origin in os.getenv(
                "AKASHI_CORS_ORIGINS",
                "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3100,http://127.0.0.1:3100,https://localhost,http://localhost,capacitor://localhost,akashi://app",
            ).split(",")
            if origin.strip()
        ),
        memory_file=memory_path,
        memory_history_limit=int(
            os.getenv("MEMORY_HISTORY_LIMIT", "20")
        ),
        memory_summary_max_chars=int(
            os.getenv("MEMORY_SUMMARY_MAX_CHARS", "4000")
        ),
        long_term_memory_file=data_path(
            "LONG_TERM_MEMORY_FILE", "long_term_memory.json"
        ),
        task_file=data_path("TASK_FILE", "tasks.json"),
        upload_dir=data_path("UPLOAD_DIR", "uploads"),
        file_index_file=data_path("FILE_INDEX_FILE", "file_index.json"),
        device_file=data_path("DEVICE_FILE", "devices.json"),
        intelligence_file=data_path("INTELLIGENCE_FILE", "private/intelligence.json"),
        schedule_file=data_path("SCHEDULE_FILE", "private/schedules.json"),
        live_state_file=data_path("LIVE_STATE_FILE", "private/live_interactions.json"),
        computer_state_file=data_path("COMPUTER_STATE_FILE", "private/computer_sessions.json"),
        autonomy_state_file=data_path("AUTONOMY_STATE_FILE", "private/autonomy_tasks.json"),
        autonomy_skill_file=data_path("AUTONOMY_SKILL_FILE", "private/autonomy_skills.json"),
        autonomy_knowledge_file=data_path("AUTONOMY_KNOWLEDGE_FILE", "private/autonomy_knowledge.json"),
        voice_state_file=data_path("VOICE_STATE_FILE", "private/voice_sessions.json"),
        phone_calls_file=data_path("PHONE_CALLS_FILE", "private/phone_calls.json"),
        max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024))),
        research_provider=os.getenv("RESEARCH_PROVIDER", "duckduckgo").strip().lower(),
        wikipedia_language=os.getenv("WIKIPEDIA_LANGUAGE", "en").strip().lower(),
        searxng_base_url=(os.getenv("SEARXNG_BASE_URL") or "").strip().rstrip("/") or None,
        research_timeout_seconds=float(os.getenv("RESEARCH_TIMEOUT_SECONDS", "20")),
        miss_minutes_enabled=os.getenv("MISS_MINUTES_ENABLED", "false").strip().casefold() in {"1", "true", "yes", "on"},
        miss_minutes_timezone=os.getenv("MISS_MINUTES_TIMEZONE", "Europe/Istanbul").strip(),
        miss_minutes_discovery_minutes=int(os.getenv("MISS_MINUTES_DISCOVERY_MINUTES", "360")),
        miss_minutes_brief_minutes=int(os.getenv("MISS_MINUTES_BRIEF_MINUTES", "1440")),
        model_fast_provider=os.getenv("AKASHI_MODEL_FAST_PROVIDER", "").strip().lower(),
        model_quality_provider=os.getenv("AKASHI_MODEL_QUALITY_PROVIDER", "").strip().lower(),
        model_reasoning_provider=os.getenv("AKASHI_MODEL_REASONING_PROVIDER", "").strip().lower(),
        model_vision_provider=vision_provider,
        model_fast_name=os.getenv("AKASHI_MODEL_FAST_NAME", "").strip(),
        model_quality_name=os.getenv("AKASHI_MODEL_QUALITY_NAME", "").strip(),
        model_reasoning_name=os.getenv("AKASHI_MODEL_REASONING_NAME", "").strip(),
        model_vision_name=vision_model,
        pairing_code_ttl_seconds=int(os.getenv("PAIRING_CODE_TTL_SECONDS", "600")),
        device_online_ttl_seconds=int(os.getenv("DEVICE_ONLINE_TTL_SECONDS", "75")),
        local_agent_base_url=os.getenv(
            "AKASHI_AGENT_URL", "http://127.0.0.1:8765"
        ).strip().rstrip("/"),
        local_agent_token=(os.getenv("AKASHI_AGENT_TOKEN") or "").strip() or None,
        local_agent_timeout_seconds=float(os.getenv("AKASHI_AGENT_TIMEOUT", "150")),
        akashi_project_path=project_path,
        computer_max_steps=max(1, min(int(os.getenv("AKASHI_COMPUTER_MAX_STEPS", "12")), 30)),
        autonomy_max_subgoals=max(5, min(int(os.getenv("AKASHI_AUTONOMY_MAX_SUBGOALS", "40")), 100)),
        autonomy_local_fallback=os.getenv("AKASHI_AUTONOMY_LOCAL_FALLBACK", "true").lower() == "true",
        expertise_db=data_path("EXPERTISE_DB", "private/expertise.sqlite3"),
        spatial_dir=data_path("SPATIAL_DIR", "private/spatial"),
        spatial_form_data_dir=(Path(os.environ["AKASHI_FORM_DATA_DIR"].strip()).expanduser().resolve()
                               if (os.getenv("AKASHI_FORM_DATA_DIR") or "").strip() else None),
        spatial_interpreter="rules" if os.getenv("AKASHI_SPATIAL_INTERPRETER", "auto").strip().lower() == "rules" else "auto",
        remote_dir=data_path("REMOTE_DIR", "private/remote") if os.getenv("REMOTE_DIR", "").strip() else None,
        remote_endpoints=tuple(
            item.strip().rstrip("/") for item in os.getenv("AKASHI_REMOTE_ENDPOINTS", "").split(",")
            if item.strip().startswith(("https://", "http://"))
        ),
        phone_enabled=os.getenv("AKASHI_PHONE_ENABLED", "false").strip().casefold() in {"1", "true", "yes", "on"},
        outbound_calls_enabled=os.getenv("AKASHI_OUTBOUND_CALLS_ENABLED", "false").strip().casefold() in {"1", "true", "yes", "on"},
        livekit_url=(os.getenv("LIVEKIT_URL") or "").strip().rstrip("/") or None,
        livekit_api_key=(os.getenv("LIVEKIT_API_KEY") or "").strip() or None,
        livekit_api_secret=(os.getenv("LIVEKIT_API_SECRET") or "").strip() or None,
        livekit_sip_outbound_trunk_id=(os.getenv("LIVEKIT_SIP_OUTBOUND_TRUNK_ID") or "").strip() or None,
        phone_agent_name=os.getenv("AKASHI_PHONE_AGENT_NAME", "akashi-phone").strip() or "akashi-phone",
        phone_worker_token=(os.getenv("AKASHI_PHONE_WORKER_TOKEN") or "").strip() or None,
        phone_core_url=os.getenv("AKASHI_PHONE_CORE_URL", "http://127.0.0.1:8000").strip().rstrip("/"),
        phone_stt_model=os.getenv("AKASHI_PHONE_STT_MODEL", "cartesia/ink-whisper").strip(),
        phone_stt_language=os.getenv("AKASHI_PHONE_STT_LANGUAGE", "tr").strip() or "tr",
        phone_tts_model=os.getenv("AKASHI_PHONE_TTS_MODEL", "cartesia/sonic-3").strip(),
        phone_tts_voice=(os.getenv("AKASHI_PHONE_TTS_VOICE") or "").strip() or None,
        phone_tts_language=os.getenv("AKASHI_PHONE_TTS_LANGUAGE", "tr").strip() or "tr",
        verimor_sip_server=os.getenv("VERIMOR_SIP_SERVER", "sip.verimor.com.tr").strip(),
        verimor_sip_username=(os.getenv("VERIMOR_SIP_USERNAME") or "").strip() or None,
        verimor_sip_password=(os.getenv("VERIMOR_SIP_PASSWORD") or "").strip() or None,
    )
