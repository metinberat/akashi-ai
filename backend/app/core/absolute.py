"""Composition root for AKASHI ABSOLUTE services.

The class coordinates focused services but intentionally keeps their storage and
execution logic in the respective modules rather than becoming a God object.
"""

from threading import Lock
from typing import List, Optional, Sequence

from app.core.brain import AkashiBrain, BrainResponse
from app.core.config import Settings, get_settings
from app.core.model_router import ModelProfile, ModelRouter
from app.core.persona import build_system_prompt
from app.computer.service import ComputerAgentService
from app.computer.store import JSONComputerStateStore
from app.computer.browser_service import SemanticBrowserAgent
from app.autonomy.engine import LongHorizonTaskEngine
from app.autonomy.knowledge import KnowledgeStore
from app.autonomy.skills import SkillLibrary
from app.autonomy.store import JSONAutonomyStore
from app.expertise.service import CharacterExpertiseService
from app.expertise.store import ExpertiseStore
from app.expertise.tools import ImproveCharacterTool, InspectCharacterImprovementTool, MaterializeCharacterTool, RefineCharacterTool
from app.expertise.training.tools import TrainYourselfTool, TrainingStatusTool, ProductionRecipeTool, TrainingControlTool, ApplyLearnedMethodTool
from app.expertise.production.host import ProductionHost
from app.expertise.production.tools import BuildCharacterTool, InspectProductionTool, PracticeProductionTool, ControlProductionTool
from app.devices.store import DeviceStore
from app.events.hub import event_hub
from app.files.service import FileIntelligenceService
from app.intelligence.scheduler import DurableScheduler, JSONScheduleStore
from app.intelligence.service import IntelligenceService
from app.intelligence.store import JSONIntelligenceStore
from app.memory.json_memory import JSONMemory
from app.memory.long_term import JSONLongTermMemory
from app.phone.service import PhoneService
from app.phone.store import JSONPhoneCallStore
from app.live.actions.base import LiveActionRuntime
from app.live.core import AkashiLiveCore
from app.live.desktop import DesktopActionGateway
from app.live.store import JSONInteractionStore
from app.research.providers import SearxNGResearchProvider, WikipediaResearchProvider, DuckDuckGoResearchProvider
from app.research.base import ResearchSource
from app.research.service import ResearchService
from app.remote.runtime import RemoteRuntime
from app.remote.tools import remote_tools
from app.spatial.service import SpatialLabService
from app.spatial.tools import spatial_tools
from app.tasks.engine import TaskEngine
from app.tasks.store import JSONTaskStore
from app.tools.builtin import (
    DeviceActionTool,
    DeviceStatusTool,
    FileReadTool,
    MemoryCreateTool,
    MemorySearchTool,
    ResearchTool,
)
from app.tools.registry import ToolRegistry
from app.voice.session import VoiceSessionManager


class AkashiCore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model_router = ModelRouter(settings)
        self.conversations = JSONMemory(settings.memory_file)
        self.memory = JSONLongTermMemory(settings.long_term_memory_file)
        self.files = FileIntelligenceService(
            settings.upload_dir,
            settings.file_index_file,
            settings.max_upload_bytes,
        )
        self.intelligence_store = JSONIntelligenceStore(settings.intelligence_file)
        self.intelligence = IntelligenceService(
            self.intelligence_store,
            settings.research_timeout_seconds,
        )
        self.schedule_store = JSONScheduleStore(settings.schedule_file)
        self.scheduler = DurableScheduler(self.schedule_store)
        self.scheduler.register("intelligence.discover", self._scheduled_discovery)
        self.scheduler.register("intelligence.daily_brief", self._scheduled_brief)
        self.schedule_store.ensure_interval(
            "miss-minutes-discovery",
            "MISS MINUTES discovery",
            "intelligence.discover",
            settings.miss_minutes_discovery_minutes,
            settings.miss_minutes_timezone,
            settings.miss_minutes_enabled,
            "run_once",
        )
        self.voice_sessions = VoiceSessionManager(settings.voice_state_file)
        self.phone_calls = JSONPhoneCallStore(settings.phone_calls_file)
        self.phone = PhoneService(settings, self.phone_calls)
        self.schedule_store.ensure_interval(
            "miss-minutes-daily-brief",
            "AKASHI Daily Intelligence",
            "intelligence.daily_brief",
            settings.miss_minutes_brief_minutes,
            settings.miss_minutes_timezone,
            settings.miss_minutes_enabled,
            "run_once",
        )
        if settings.research_provider == "searxng":
            if not settings.searxng_base_url:
                raise RuntimeError("RESEARCH_PROVIDER=searxng requires SEARXNG_BASE_URL.")
            research_provider = SearxNGResearchProvider(
                settings.searxng_base_url,
                settings.research_timeout_seconds,
            )
        elif settings.research_provider == "duckduckgo":
            research_provider = DuckDuckGoResearchProvider(settings.research_timeout_seconds)
        elif settings.research_provider == "wikipedia":
            research_provider = WikipediaResearchProvider(
                settings.wikipedia_language,
                settings.research_timeout_seconds,
            )
        else:
            raise RuntimeError(
                f"Unsupported RESEARCH_PROVIDER '{settings.research_provider}'."
            )
        self.research = ResearchService(research_provider, self._synthesize_research)
        self.devices = DeviceStore(
            settings.device_file,
            settings.pairing_code_ttl_seconds,
            settings.device_online_ttl_seconds,
        )
        self.tools = ToolRegistry()
        for tool in (
            MemorySearchTool(self.memory),
            MemoryCreateTool(self.memory),
            FileReadTool(self.files),
            ResearchTool(self.research),
            DeviceStatusTool(self.devices),
            DeviceActionTool(self.devices),
        ):
            self.tools.register(tool)
        self.tasks = TaskEngine(JSONTaskStore(settings.task_file), self.tools, event_hub)
        default_provider = self.model_router.provider_for("quality")
        self.brain = AkashiBrain(
            default_provider,
            self.conversations,
            long_term_memory=self.memory,
            files=self.files,
        )
        self.desktop = DesktopActionGateway(settings, self.devices)
        self.computer = ComputerAgentService(
            self.desktop,
            self.model_router,
            event_hub,
            JSONComputerStateStore(settings.computer_state_file),
            settings.computer_max_steps,
        )
        self.autonomy_skills = SkillLibrary(settings.autonomy_skill_file)
        self.autonomy_knowledge = KnowledgeStore(settings.autonomy_knowledge_file)
        self.expertise = CharacterExpertiseService(ExpertiseStore(settings.expertise_db), self.autonomy_knowledge)
        self.expertise.attach_skill_library(self.autonomy_skills)
        self.production_host = ProductionHost(self.expertise.production, self.desktop)
        self.tools.register(BuildCharacterTool(self.production_host, self.model_router))
        self.tools.register(InspectProductionTool(self.production_host))
        self.tools.register(PracticeProductionTool(self.expertise.production))
        self.tools.register(ControlProductionTool(self.production_host))
        for tool in (ImproveCharacterTool(self.expertise.workshop), InspectCharacterImprovementTool(self.expertise.workshop),
                     MaterializeCharacterTool(self.expertise.workshop, self.desktop), RefineCharacterTool(self.expertise.workshop, self.desktop),
                     TrainYourselfTool(self.expertise), TrainingStatusTool(self.expertise), ProductionRecipeTool(self.expertise),
                     TrainingControlTool(self.expertise), ApplyLearnedMethodTool(self.expertise)):
            self.tools.register(tool)
        self.autonomy_knowledge.expert_search = self.expertise.retrieve
        self.spatial = SpatialLabService(
            settings.spatial_dir,
            form_data_dir=settings.spatial_form_data_dir,
            events=event_hub,
            model_provider=lambda: self.model_router.provider_for("fast"),
            interpreter=settings.spatial_interpreter,
        )
        for tool in spatial_tools(self.spatial):
            self.tools.register(tool)
        self.autonomy = LongHorizonTaskEngine(
            JSONAutonomyStore(settings.autonomy_state_file),
            self.computer,
            self.model_router,
            event_hub,
            self.autonomy_skills,
            self.autonomy_knowledge,
            max_subgoals=settings.autonomy_max_subgoals,
            browser=SemanticBrowserAgent(self.desktop, self.model_router),
            experience_sink=self.expertise.record_experience,
        )
        self.remote = RemoteRuntime(
            self.devices,
            directory=settings.remote_dir or settings.spatial_dir.parent / "remote",
            spatial=self.spatial,
            tasks=self.tasks,
            autonomy=self.autonomy,
            voice_sessions=self.voice_sessions,
            chat=self.chat,
            events=event_hub,
            endpoints=settings.remote_endpoints,
        )
        for tool in remote_tools(self.remote):
            self.tools.register(tool)
        self.live = AkashiLiveCore(
            LiveActionRuntime(
                settings=settings,
                desktop=self.desktop,
                brain=self.brain,
                model_router=self.model_router,
                computer=self.computer,
                autonomy=self.autonomy,
                spatial=self.spatial,
                remote=self.remote,
            ),
            event_hub,
            JSONInteractionStore(settings.live_state_file),
        )

    async def _scheduled_discovery(self) -> dict:
        result = await self.intelligence.discover()
        summary = {
            "status": result["status"],
            "sources_checked": result["sources_checked"],
            "created": result["created"],
            "merged": result["merged"],
            "failure_count": len(result["failures"]),
        }
        await event_hub.publish("intelligence.discovery.completed", summary)
        return summary

    async def _scheduled_brief(self) -> dict:
        brief = self.intelligence.create_daily_brief()
        summary = {
            "status": brief["status"],
            "brief_id": brief["id"],
            "item_count": brief["item_count"],
        }
        await event_hub.publish("intelligence.brief.completed", summary)
        return summary

    async def _synthesize_research(
        self,
        question: str,
        sources: Sequence[ResearchSource],
    ) -> str:
        source_blocks: List[str] = []
        for index, source in enumerate(sources, start=1):
            source_blocks.append(
                f"SOURCE {index}\nTitle: {source.title}\nURL: {source.url}\n"
                f"Extract: {source.snippet[:1800]}"
            )
        prompt = (
            f"Research question: {question}\n\n"
            + "\n\n".join(source_blocks)
            + "\n\nSynthesize a concise answer in the user's language. "
            "Use only the supplied source extracts. Mark source support with [1], [2], etc. "
            "Do not invent facts or citations. State when the extracts are insufficient."
        )
        provider = self.model_router.provider_for("reasoning")
        if provider.name == "mock":
            raise RuntimeError("Mock mode cannot synthesize research evidence.")
        return await provider.generate(
            message=prompt,
            system_prompt=build_system_prompt("public"),
            history=[],
            intent="research",
        )

    async def chat(
        self,
        message: str,
        session_id: str,
        mode: str,
        profile: ModelProfile = "quality",
        file_ids: Optional[Sequence[str]] = None,
        voice: bool = False,
        images: Optional[Sequence[str]] = None,
        interaction_id: Optional[str] = None,
    ) -> BrainResponse:
        return await self.live.respond(
            message=message,
            session_id=session_id,
            mode=mode,
            voice=voice,
            interaction_id=interaction_id,
            fallback=lambda: self.brain.respond(
                message=message,
                session_id=session_id,
                mode=mode,  # type: ignore[arg-type]
                provider=self.model_router.provider_for(profile),
                file_ids=file_ids,
                voice=voice,
                images=images,
                profile=profile,
            ),
        )


_core_instance: Optional[AkashiCore] = None
_core_lock = Lock()


def get_core() -> AkashiCore:
    """Return one process-wide Core, including during concurrent first requests."""
    global _core_instance
    if _core_instance is None:
        with _core_lock:
            if _core_instance is None:
                _core_instance = AkashiCore(get_settings())
    return _core_instance
