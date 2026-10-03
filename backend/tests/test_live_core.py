import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

from app.core.brain import AkashiBrain, BrainResponse
from app.core.config import Settings
from app.core.model_router import ModelRouter
from app.live.actions.base import LiveActionRuntime
from app.live.core import InteractionCancelled, InteractionManager
from app.live.registry import LiveActionRegistry
from app.live.store import JSONInteractionStore
from app.memory.json_memory import JSONMemory
from app.providers.mock import MockProvider


class FakeDesktop:
    async def execute(
        self,
        action: str,
        arguments: Dict[str, Any],
        approved: bool,
    ) -> Dict[str, Any]:
        if action != "get_system_status":
            raise RuntimeError("fixture supports telemetry only")
        return {
            "ok": True,
            "data": {
                "cpu": {"usage_percent": 8},
                "memory": {
                    "total_bytes": 32 * 1024 ** 3,
                    "available_bytes": 20 * 1024 ** 3,
                },
                "disk": {"usage_percent": 44},
                "uptime_seconds": 7200,
                "network_online": True,
                "gpu": {
                    "available": True,
                    "devices": [{
                        "name": "NVIDIA RTX fixture",
                        "usage_percent": 3,
                        "temperature_c": 63,
                        "memory_used_mb": 1200,
                        "memory_total_mb": 16384,
                    }],
                },
            },
        }


class LiveActionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        settings = Settings(ai_provider="mock", memory_file=root / "memory.json")
        brain = AkashiBrain(MockProvider(), JSONMemory(settings.memory_file))
        runtime = LiveActionRuntime(
            settings=settings,
            desktop=FakeDesktop(),  # type: ignore[arg-type]
            brain=brain,
            model_router=ModelRouter(settings),
        )
        self.registry = LiveActionRegistry(runtime)

    def test_action_modules_are_discovered_with_structured_metadata(self) -> None:
        definitions = {item["name"]: item for item in self.registry.definitions()}
        self.assertEqual(
            set(definitions),
            {
                "application.open",
                "project.open_akashi",
                "system.status",
                "vision.camera",
                "vision.screen",
                "computer.goal",
                "autonomy.goal",
                "spatial.scene",
            },
        )
        for definition in definitions.values():
            self.assertIn(definition["risk"], {"safe", "confirm", "restricted"})
            self.assertTrue(definition["capabilities"])
            self.assertEqual(definition["input_schema"]["type"], "object")

    def test_natural_turkish_and_english_action_selection(self) -> None:
        fixtures = {
            "Bilgisayarın durumunu söyle.": "system.status",
            "GPU kaç derece?": "system.status",
            "VS Code'u aç.": "application.open",
            "AKASHI projesini aç.": "project.open_akashi",
            "Ekranıma bak ve ne gördüğünü söyle.": "vision.screen",
            "Look through the camera.": "vision.camera",
            "Open Discord, find the project page, then return to VS Code.": "computer.goal",
            "Look at the screen and click the visible Continue button.": "computer.goal",
            "Inspect the references, modify the asset, build it, test it, then verify and finish the entire objective.": "autonomy.goal",
        }
        for message, expected in fixtures.items():
            selected = self.registry.select(message)
            self.assertIsNotNone(selected, message)
            self.assertEqual(selected[0].definition.name, expected)  # type: ignore[index]
        self.assertIsNone(self.registry.select("FastAPI dersini bana anlat."))
        self.assertIsNone(self.registry.select("How do I open VS Code?"))
        self.assertIsNone(self.registry.select("How to open the AKASHI project"))

    async def test_system_status_response_uses_runtime_measurements(self) -> None:
        action, match = self.registry.select("Bilgisayarın durumu ne?")  # type: ignore[misc]
        result = await action.execute(
            "Bilgisayarın durumu ne?", "fixture", "private", False, match
        )
        self.assertEqual(result.provider, "windows-agent")
        for value in ("CPU 8%", "GPU 3%", "GPU 63°C", "VRAM 1.2 GB/16 GB", "RAM 12 GB/32 GB"):
            self.assertIn(value, result.text)


class InteractionManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_cancel_stops_the_active_interaction(self) -> None:
        manager = InteractionManager()

        async def slow() -> BrainResponse:
            await asyncio.sleep(30)
            raise AssertionError("cancel did not stop the operation")

        task = asyncio.create_task(manager.run("interaction-1", "session", slow))
        await asyncio.sleep(0)
        self.assertTrue(await manager.cancel("interaction-1"))
        with self.assertRaises(InteractionCancelled):
            await task

    async def test_completed_state_survives_restart_without_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "live.json"
            manager = InteractionManager(JSONInteractionStore(path))

            async def complete() -> BrainResponse:
                return BrainResponse(
                    text="private answer that must not be persisted",
                    session_id="session",
                    provider="mock",
                    intent="casual",
                )

            await manager.run("interaction-complete", "session", complete)
            recovered = JSONInteractionStore(path)
            item = recovered.get("interaction-complete")
            self.assertEqual(item["status"], "completed")  # type: ignore[index]
            serialized = path.read_text(encoding="utf-8")
            self.assertNotIn("private answer", serialized)

    def test_running_state_is_honestly_interrupted_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "live.json"
            store = JSONInteractionStore(path)
            store.start("interaction-running", "session")
            recovered = JSONInteractionStore(path)
            self.assertEqual(recovered.get("interaction-running")["status"], "running")  # type: ignore[index]
            recovered.recover_interrupted()
            item = recovered.get("interaction-running")
            self.assertEqual(  # type: ignore[index]
                item["status"], "interrupted_by_restart"
            )


if __name__ == "__main__":
    unittest.main()
