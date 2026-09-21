import unittest
import tempfile
from pathlib import Path

from app.voice.session import VoiceSessionManager


class VoiceSessionTests(unittest.TestCase):
    def test_complete_lifecycle_and_barge_in_generation(self):
        manager = VoiceSessionManager()
        session = manager.start("conversation", "tr")
        session = manager.transition(session["id"], "transcribing", last_user_utterance="Durumu söyle")
        session = manager.transition(session["id"], "thinking", interaction_id="interaction-1")
        session = manager.transition(session["id"], "acting")
        session = manager.transition(session["id"], "speaking", last_assistant_utterance="Sistem boşta")
        interrupted = manager.interrupt(session["id"])
        self.assertEqual(interrupted["state"], "interrupted")
        self.assertEqual(interrupted["generation"], 2)
        self.assertIsNone(interrupted["interaction_id"])
        listening = manager.transition(session["id"], "listening")
        self.assertEqual(listening["state"], "listening")
        self.assertTrue(manager.stop(session["id"]))

    def test_invalid_stale_transition_is_rejected(self):
        manager = VoiceSessionManager()
        session = manager.start("conversation")
        with self.assertRaises(ValueError):
            manager.transition(session["id"], "speaking")

    def test_restart_interrupts_session_without_persisting_utterances(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "voice.json"
            manager = VoiceSessionManager(path)
            session = manager.start("conversation", "tr")
            manager.transition(
                session["id"],
                "transcribing",
                last_user_utterance="private spoken text",
            )
            recovered = VoiceSessionManager(path)
            self.assertEqual(recovered.get(session["id"])["state"], "transcribing")  # type: ignore[index]
            recovered.recover_after_restart()
            item = recovered.get(session["id"])
            self.assertEqual(item["state"], "interrupted")  # type: ignore[index]
            self.assertIsNone(item["last_user_utterance"])  # type: ignore[index]
            self.assertNotIn("private spoken text", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
