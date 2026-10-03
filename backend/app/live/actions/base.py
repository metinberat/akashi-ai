from abc import ABC, abstractmethod
from dataclasses import dataclass
import re
import unicodedata
from typing import Optional, TYPE_CHECKING

from app.core.brain import AkashiBrain, BrainResponse
from app.core.config import Settings
from app.core.model_router import ModelRouter
from app.live.desktop import DesktopActionGateway
from app.live.models import ActionMatch, LiveActionDefinition

if TYPE_CHECKING:
    from app.autonomy.engine import LongHorizonTaskEngine
    from app.computer.service import ComputerAgentService
    from app.spatial.service import SpatialLabService


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(
        character for character in normalized
        if not unicodedata.combining(character)
    )
    return re.sub(r"\s+", " ", without_marks.replace("ı", "i")).strip()


def is_turkish(value: str) -> bool:
    normalized = normalize_text(value)
    markers = {
        "ac", "bak", "bilgisayar", "durum", "ekran", "kamera", "kac",
        "proje", "gordugunu", "sicaklik", "soyle",
    }
    return bool(markers.intersection(normalized.split())) or any(
        character in value for character in "çğıöşüÇĞİÖŞÜ"
    )


@dataclass(frozen=True)
class LiveActionRuntime:
    settings: Settings
    desktop: DesktopActionGateway
    brain: AkashiBrain
    model_router: ModelRouter
    computer: Optional["ComputerAgentService"] = None
    autonomy: Optional["LongHorizonTaskEngine"] = None
    spatial: Optional["SpatialLabService"] = None


class LiveAction(ABC):
    definition: LiveActionDefinition

    @abstractmethod
    def match(self, message: str) -> Optional[ActionMatch]:
        raise NotImplementedError

    @abstractmethod
    async def execute(
        self,
        message: str,
        session_id: str,
        mode: str,
        voice: bool,
        match: ActionMatch,
    ) -> BrainResponse:
        raise NotImplementedError

    def failure_text(self, message: str, error: Exception) -> str:
        detail = str(error).strip() or "Desktop action failed."
        if is_turkish(message):
            translations = {
                "Desktop agent offline.": "Desktop agent çevrimdışı.",
                "Desktop action failed.": "Desktop eylemi başarısız.",
                "Application is not in the discovered allowlist.": "Uygulama güvenli kayıt listesinde bulunamadı.",
                "No camera frame could be captured.": "Kameradan görüntü alınamadı.",
                "No camera is available.": "Kullanılabilir kamera bulunamadı.",
            }
            return translations.get(detail, detail)
        return detail

