import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

from app.autonomy.engine import LongHorizonTaskEngine
from app.autonomy.knowledge import KnowledgeStore
from app.autonomy.skills import SkillLibrary
from app.autonomy.store import JSONAutonomyStore
from app.events.hub import EventHub


class FakeComputer:
    def __init__(self, fail_first: bool = False) -> None:
        self.calls = []
        self.fail_first = fail_first

    async def run(self, goal: str, session_id: str, approved: bool, task_id: str = "") -> Dict[str, Any]:
        self.calls.append({"goal": goal, "session_id": session_id, "approved": approved, "task_id": task_id})
        if self.fail_first and len(self.calls) == 1:
            return {"status": "failed", "summary": "Visible output was missing."}
        return {"status": "completed", "summary": "Real outcome observed and verified."}

    async def cancel(self, _session_id: str) -> bool:
        return True


class AutonomyV2Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.store = JSONAutonomyStore(root / "tasks.json")
        self.skills = SkillLibrary(root / "skills.json")
        self.knowledge = KnowledgeStore(root / "knowledge.json")

    async def test_goal_graph_executes_dependencies_and_extracts_skill_candidate(self) -> None:
        phases = []

        async def decision(phase: str, context: Dict[str, Any]) -> Dict[str, Any]:
            phases.append(phase)
            if phase == "plan":
                return {"subgoals": [
                    {"id": "research", "title": "Inspect evidence", "description": "Open the browser and inspect the reference.", "channel": "browser", "depends_on": [], "acceptance": "Reference title and URL are observed."},
                    {"id": "artifact", "title": "Create artifact", "description": "Create and verify the requested artifact.", "channel": "filesystem", "depends_on": ["research"], "acceptance": "Artifact exists at the verified path."},
                ]}
            if phase == "evaluate":
                title = context["subgoal"]["title"]
                return {"verdict": "passed", "summary": f"{title} verified.", "artifacts": [{"kind": "file", "value": "C:/safe/result.txt", "verified": True}]}
            return {"verdict": "passed", "summary": "Entire objective verified."}

        computer = FakeComputer()
        engine = LongHorizonTaskEngine(self.store, computer, object(), EventHub(), self.skills, self.knowledge, decision=decision)  # type: ignore[arg-type]
        created = await engine.create("Research the reference and create a verified artifact.", "session", approved=True)
        result = await engine.wait(created["id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual([node["status"] for node in result["subgoals"]], ["completed", "completed"])
        self.assertEqual(len(computer.calls), 2)
        self.assertEqual(phases, ["plan", "evaluate", "evaluate", "final"])
        self.assertTrue(result.get("skill_candidate_id"))
        self.assertEqual(self.skills.list()[0]["status"], "candidate")
        self.assertNotIn("base64", str(result))

    async def test_failed_action_reobserves_and_retries_before_success(self) -> None:
        evaluations = 0

        async def decision(phase: str, _context: Dict[str, Any]) -> Dict[str, Any]:
            nonlocal evaluations
            if phase == "plan":
                return {"subgoals": [{"id": "operate", "title": "Operate app", "description": "Perform and verify the operation.", "channel": "application", "depends_on": [], "acceptance": "Expected visible state exists."}]}
            if phase == "evaluate":
                evaluations += 1
                return {"verdict": "retry" if evaluations == 1 else "passed", "summary": "Retry with fresh observation." if evaluations == 1 else "Visible state verified.", "correction": "Re-observe and use the semantic adapter."}
            return {"verdict": "passed", "summary": "Recovered and completed."}

        computer = FakeComputer(fail_first=True)
        engine = LongHorizonTaskEngine(self.store, computer, object(), EventHub(), self.skills, self.knowledge, decision=decision)  # type: ignore[arg-type]
        task = await engine.create("Operate the application and recover if its state changes.", "session", approved=True)
        result = await engine.wait(task["id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(computer.calls), 2)
        self.assertTrue(any(event["kind"] == "retry" for event in result["events"]))

    def test_restart_is_checkpointed_without_assuming_inflight_success(self) -> None:
        task = {
            "id": "operator-restart", "session_id": "s", "goal": "test", "title": "test",
            "status": "running", "revision": 0, "updated_at": "", "events": [], "artifacts": [],
            "subgoals": [{"id": "step", "status": "running", "error": None}],
        }
        self.store.create(task)
        recovered = JSONAutonomyStore(self.store.path).get("operator-restart")
        self.assertEqual(recovered["status"], "paused_recovery")  # type: ignore[index]
        self.assertEqual(recovered["subgoals"][0]["status"], "pending")  # type: ignore[index]

    def test_knowledge_is_retrieved_as_untrusted_evidence(self) -> None:
        self.knowledge.ingest("Blender export notes", "Use glTF export and verify the generated file.", "local-note", "project")
        results = self.knowledge.search("Blender glTF export")
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["untrusted"])

    async def test_replan_rewires_downstream_dependencies_and_finishes(self):
        async def decision(phase, context):
            if phase == "plan":
                return {"subgoals": [{"id": "a", "title": "A", "description": "first", "depends_on": []}, {"id": "b", "title": "B", "description": "second", "depends_on": ["a"]}]}
            if phase == "evaluate":
                return {"verdict": "replan" if context["subgoal"]["title"] == "A" else "passed", "summary": "Observed result"}
            if phase == "replan":
                return {"subgoals": [{"id": "recover", "title": "Recover A", "description": "alternative", "depends_on": []}]}
            return {"verdict": "passed", "summary": "All outcomes verified."}
        computer = FakeComputer(fail_first=True)
        engine = LongHorizonTaskEngine(self.store, computer, object(), EventHub(), self.skills, self.knowledge, decision=decision)
        task = await engine.create("multi app operation", "s", True)
        result = await engine.wait(task["id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual([node["status"] for node in result["subgoals"]], ["superseded", "completed", "completed"])
        self.assertEqual(len(computer.calls), 3)

    async def test_final_rejection_continues_recovery_instead_of_exiting(self):
        finals = 0
        async def decision(phase, context):
            nonlocal finals
            if phase in {"plan", "replan"}:
                return {"subgoals": [{"id": "a", "title": "Repair output", "description": "operation", "depends_on": []}]}
            if phase == "final":
                finals += 1
                return {"verdict": "replan" if finals == 1 else "passed", "summary": "Acceptance checked."}
            return {"verdict": "passed", "summary": "Verified"}
        engine = LongHorizonTaskEngine(self.store, FakeComputer(), object(), EventHub(), self.skills, self.knowledge, decision=decision)
        task = await engine.create("verify final objective", "s", True)
        self.assertEqual((await engine.wait(task["id"]))["status"], "completed")
        self.assertEqual(finals, 2)

    async def test_shutdown_checkpoints_running_job_and_resume_finishes(self):
        entered = asyncio.Event()
        class Slow(FakeComputer):
            async def run(self, *args, **kwargs):
                entered.set()
                await asyncio.Event().wait()
        async def decision(phase, context):
            if phase == "plan": return {"subgoals": [{"id": "a", "title": "A", "description": "operate"}]}
            return {"verdict": "passed", "summary": "Verified"}
        engine = LongHorizonTaskEngine(self.store, Slow(), object(), EventHub(), self.skills, self.knowledge, decision=decision)
        task = await engine.create("operation", "s", True)
        await asyncio.wait_for(entered.wait(), 2)
        await engine.shutdown()
        checkpoint = self.store.get(task["id"])
        self.assertEqual(checkpoint["status"], "paused_recovery")
        self.assertEqual(checkpoint["subgoals"][0]["status"], "pending")
        engine.computer = FakeComputer()
        await engine.resume(task["id"])
        self.assertEqual((await engine.wait(task["id"]))["status"], "completed")

    def test_invalid_graph_dependencies_are_rejected(self):
        engine = LongHorizonTaskEngine(self.store, FakeComputer(), object(), EventHub(), self.skills, self.knowledge)
        for graph in ([{"id": "a", "depends_on": ["unknown"]}], [{"id": "a"}, {"id": "a"}], [{"id": "a", "depends_on": ["b"]}, {"id": "b", "depends_on": ["a"]}]):
            with self.assertRaises(RuntimeError): engine._normalize_plan({"subgoals": graph})

    def test_semantic_locator_does_not_guess_ambiguous_or_missing_targets(self):
        from app.computer.browser_service import SemanticBrowserAgent
        snapshot = {"elements": [{"index": 1, "text": "Save"}, {"index": 2, "text": "Save"}]}
        args = {"operation": "click", "target": {"text": "Save"}}
        self.assertEqual(SemanticBrowserAgent._resolve_target(args, snapshot, "click save"), args)
        self.assertEqual(SemanticBrowserAgent._resolve_target({"operation": "click"}, snapshot, "test"), {"operation": "click"})

    async def test_artifact_claim_requires_real_filesystem_evidence(self):
        class Gateway:
            async def execute(self, name, arguments, approved):
                self.assertions = (name, arguments, approved)
                return {"data": {"is_directory": False, "size": 20}}
        computer = FakeComputer()
        computer.desktop = Gateway()
        engine = LongHorizonTaskEngine(self.store, computer, object(), EventHub(), self.skills, self.knowledge)
        task = {"artifacts": []}
        engine._merge_entities_artifacts(task, {"artifacts": [{"kind": "render", "value": "approved/result.png", "verified": True}]}, "s")
        self.assertFalse(task["artifacts"][0]["verified"])
        await engine._verify_artifacts(task)
        self.assertTrue(task["artifacts"][0]["verified"])
        self.assertEqual(computer.desktop.assertions[0], "file_metadata")

    def test_configured_cloud_failure_can_use_local_reasoning_provider(self):
        from app.core.config import Settings
        from app.core.model_router import ModelRouter
        router = ModelRouter(Settings(ai_provider="mock", model_reasoning_provider="gemini", gemini_api_key=None, autonomy_local_fallback=True))
        self.assertEqual([provider.name for provider in router.reasoning_candidates()], ["ollama"])

    async def test_browser_waits_for_explicit_task_approval_without_model_call(self):
        from app.computer.browser_service import SemanticBrowserAgent
        result = await SemanticBrowserAgent(object(), object()).run("inspect site", approved=False)
        self.assertEqual(result["status"], "awaiting_confirmation")

    def test_entity_versions_preserve_previous_reference(self):
        task = {}
        for step, value in (("first", "original.blend"), ("second", "corrected.blend")):
            LongHorizonTaskEngine._merge_entities_artifacts(task, {"entities": {"character": {"kind": "file", "value": value}}}, step)
        self.assertEqual(task["entities"]["character"]["value"], "corrected.blend")
        self.assertEqual(task["entities"]["character"]["history"][0]["value"], "original.blend")


if __name__ == "__main__":
    unittest.main()
