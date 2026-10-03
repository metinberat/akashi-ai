import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

from app.computer.service import ComputerAgentService
from app.computer.store import JSONComputerStateStore
from app.events.hub import EventHub


class FakeDesktop:
    def __init__(self, terminal: bool = False) -> None:
        process = "cmd.exe" if terminal else "notepad.exe"
        self.state = {
            "virtual_screen": {"x": 0, "y": 0, "width": 1920, "height": 1080},
            "cursor": {"x": 10, "y": 10},
            "foreground_window_id": 42,
            "windows": [{
                "window_id": 42,
                "title": "Controlled test window",
                "process_name": process,
                "foreground": True,
            }],
        }
        self.calls = []

    async def execute(self, action: str, arguments: Dict[str, Any], approved: bool) -> Dict[str, Any]:
        self.calls.append((action, arguments, approved))
        if action == "get_desktop_state":
            return {"ok": True, "data": self.state}
        if action == "take_screenshot":
            return {"ok": True, "data": {
                "base64": "aW1hZ2U=", "width": 1600, "height": 900,
                "original_width": 1920, "original_height": 1080,
                "virtual_screen": self.state["virtual_screen"],
            }}
        return {"ok": True, "data": {"operation": arguments.get("operation"), "verified": True}}


class ComputerAgentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = JSONComputerStateStore(Path(self.temporary.name) / "computer.json")

    async def test_observe_act_verify_loop_persists_only_bounded_evidence(self) -> None:
        decisions = iter([
            {"status": "act", "action": {"name": "window_control", "arguments": {"operation": "focus", "window_id": 42}}},
            {"status": "complete", "summary": "Test window focused and verified."},
        ])

        async def planner(_goal, state, image, history):
            self.assertEqual(state["foreground_window_id"], 42)
            self.assertEqual(image, "aW1hZ2U=")
            return next(decisions)

        desktop = FakeDesktop()
        service = ComputerAgentService(desktop, object(), EventHub(), self.store, planner=planner)  # type: ignore[arg-type]
        result = await service.run("Focus the controlled test window.", "session-test", approved=True)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["steps"][0]["action"], "window_control")
        self.assertTrue(result["steps"][0]["verified"])
        self.assertNotIn("base64", str(result))
        self.assertIn(("window_control", {"operation": "focus", "window_id": 42}, True), desktop.calls)

    async def test_state_changing_action_requires_approval(self) -> None:
        async def planner(_goal, _state, _image, _history):
            return {"status": "act", "action": {"name": "computer_input", "arguments": {"operation": "click", "x": 10, "y": 10}}}

        service = ComputerAgentService(FakeDesktop(), object(), EventHub(), self.store, planner=planner)  # type: ignore[arg-type]
        with self.assertRaises(PermissionError):
            await service.run("Click the visible button.", "session-denied", approved=False)
        self.assertEqual(self.store.get("session-denied")["status"], "failed")  # type: ignore[index]

    async def test_generic_terminal_typing_is_blocked(self) -> None:
        async def planner(_goal, _state, _image, _history):
            return {"status": "act", "action": {"name": "computer_input", "arguments": {"operation": "type_text", "text": "whoami"}}}

        service = ComputerAgentService(FakeDesktop(terminal=True), object(), EventHub(), self.store, planner=planner)  # type: ignore[arg-type]
        with self.assertRaises(PermissionError):
            await service.run("Type into the current window.", "session-terminal", approved=True)

    async def test_consequential_submission_stops_before_input(self) -> None:
        async def planner(_goal, _state, _image, _history):
            return {"status": "act", "action": {"name": "computer_input", "arguments": {"operation": "click", "x": 10, "y": 10}}}

        desktop = FakeDesktop()
        service = ComputerAgentService(desktop, object(), EventHub(), self.store, planner=planner)  # type: ignore[arg-type]
        with self.assertRaises(PermissionError):
            await service.run("Submit the purchase.", "session-submit", approved=True)
        self.assertFalse(any(call[0] == "computer_input" for call in desktop.calls))

    async def test_recent_computer_context_is_available_to_next_goal(self) -> None:
        self.store.begin("first-task", "session-context", "Open the file")
        self.store.update(
            "session-context",
            status="completed",
            context={"foreground": {"title": "notes.txt"}, "recent_actions": [{"action": "read_text_file", "evidence": {"path": "C:/safe/notes.txt"}}]},
        )

        async def planner(_goal, state, _image, history):
            self.assertEqual(state["session_context"]["foreground"]["title"], "notes.txt")
            self.assertEqual(history[0]["evidence"]["path"], "C:/safe/notes.txt")
            return {"status": "complete", "summary": "Context resolved."}

        service = ComputerAgentService(FakeDesktop(), object(), EventHub(), self.store, planner=planner)  # type: ignore[arg-type]
        result = await service.run("Open that again.", "session-context", approved=True)
        self.assertEqual(result["status"], "completed")

    def test_planner_json_parser_rejects_non_json_and_accepts_fences(self) -> None:
        value = ComputerAgentService._parse_decision('```json\n{"status":"complete","summary":"done"}\n```')
        self.assertEqual(value["status"], "complete")
        with self.assertRaises(RuntimeError):
            ComputerAgentService._parse_decision("click the button")


if __name__ == "__main__":
    unittest.main()
