from typing import Any, Dict, List, Optional

from app.core.brain import BrainResponse
from app.core.intent import analyze_intent
from app.live.actions.base import LiveAction, LiveActionRuntime, is_turkish, normalize_text
from app.live.models import ActionMatch, LiveActionDefinition


def _number(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _metric(value: Optional[float], suffix: str = "") -> str:
    if value is None:
        return "—"
    rounded = round(value, 1)
    return f"{int(rounded) if rounded.is_integer() else rounded:g}{suffix}"


def _gib(value: Any) -> Optional[float]:
    number = _number(value)
    return None if number is None else number / (1024 ** 3)


def _mib_to_gib(value: Any) -> Optional[float]:
    number = _number(value)
    return None if number is None else number / 1024


class SystemStatusAction(LiveAction):
    definition = LiveActionDefinition(
        name="system.status",
        description="Read live CPU, RAM, disk, network, uptime and NVIDIA GPU telemetry.",
        input_schema={"type": "object", "additionalProperties": False},
        risk="safe",
        capabilities=("system", "telemetry", "gpu"),
        examples=(
            "Bilgisayarın durumu ne?",
            "GPU kaç derece?",
            "Show system status.",
        ),
    )

    def __init__(self, runtime: LiveActionRuntime) -> None:
        self.runtime = runtime

    def match(self, message: str) -> Optional[ActionMatch]:
        text = normalize_text(message)
        strong = (
            "bilgisayarin durumu", "sistem durumu", "pc durumu",
            "system status", "computer status", "system health",
        )
        metrics = (
            "cpu", "gpu", "ram", "vram", "ekran karti", "uptime",
            "sicaklik", "temperature", "bellek kullanimi",
        )
        if any(phrase in text for phrase in strong):
            return ActionMatch(score=100, arguments={})
        if any(metric in text for metric in metrics) and any(
            cue in text for cue in ("kac", "ne", "durum", "usage", "status", "how", "show", "tell")
        ):
            return ActionMatch(score=90, arguments={})
        return None

    async def execute(
        self,
        message: str,
        session_id: str,
        mode: str,
        voice: bool,
        match: ActionMatch,
    ) -> BrainResponse:
        result = await self.runtime.desktop.execute("get_system_status", {}, False)
        data = result.get("data", {})
        cpu = data.get("cpu", {}) if isinstance(data, dict) else {}
        memory = data.get("memory", {}) if isinstance(data, dict) else {}
        disk = data.get("disk", {}) if isinstance(data, dict) else {}
        gpu = data.get("gpu", {}) if isinstance(data, dict) else {}
        devices = gpu.get("devices", []) if isinstance(gpu, dict) else []
        gpu_device = devices[0] if isinstance(devices, list) and devices else {}

        total_ram = _gib(memory.get("total_bytes")) if isinstance(memory, dict) else None
        available_ram = _gib(memory.get("available_bytes")) if isinstance(memory, dict) else None
        used_ram = (
            total_ram - available_ram
            if total_ram is not None and available_ram is not None
            else None
        )
        uptime_seconds = _number(data.get("uptime_seconds")) if isinstance(data, dict) else None
        uptime_hours = None if uptime_seconds is None else uptime_seconds / 3600
        parts: List[str] = [
            f"CPU {_metric(_number(cpu.get('usage_percent')) if isinstance(cpu, dict) else None, '%')}",
        ]
        if isinstance(gpu, dict) and gpu.get("available") and isinstance(gpu_device, dict):
            parts.extend(
                [
                    f"GPU {_metric(_number(gpu_device.get('usage_percent')), '%')}",
                    f"GPU {_metric(_number(gpu_device.get('temperature_c')), '°C')}",
                    "VRAM "
                    + _metric(_mib_to_gib(gpu_device.get("memory_used_mb")), " GB")
                    + "/"
                    + _metric(_mib_to_gib(gpu_device.get("memory_total_mb")), " GB"),
                ]
            )
        else:
            parts.append("GPU telemetry unavailable")
        parts.append(f"RAM {_metric(used_ram, ' GB')}/{_metric(total_ram, ' GB')}")
        parts.append(
            f"Disk {_metric(_number(disk.get('usage_percent')) if isinstance(disk, dict) else None, '%')}"
        )
        parts.append(f"Uptime {_metric(uptime_hours, ' h')}")
        if is_turkish(message):
            parts[-1] = f"Çalışma süresi {_metric(uptime_hours, ' saat')}"
            parts.append("Ağ çevrimiçi" if data.get("network_online") else "Ağ durumu bilinmiyor")
        else:
            parts.append("Network online" if data.get("network_online") else "Network state unknown")
        text = ", ".join(parts) + "."
        intent = analyze_intent(message)
        self.runtime.brain.record_runtime_exchange(
            session_id, message, text, intent, mode  # type: ignore[arg-type]
        )
        return BrainResponse(text=text, session_id=session_id, provider="windows-agent", intent=intent)


def create_actions(runtime: LiveActionRuntime) -> List[LiveAction]:
    return [SystemStatusAction(runtime)]
