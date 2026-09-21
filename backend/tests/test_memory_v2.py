import json
import tempfile
import unittest
from pathlib import Path

from app.memory.json_memory import JSONMemory
from app.memory.long_term import JSONLongTermMemory, SensitiveMemoryError


class LongTermMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = JSONLongTermMemory(Path(self.temporary.name) / "memory.json")

    def test_crud_and_relevance_retrieval(self) -> None:
        preference = self.store.create(
            "I prefer concise technical explanations.",
            category="preference",
            tags=["writing", "technical"],
        )
        self.store.create("The garden gate is green.", category="fact")
        matches = self.store.retrieve("technical explanation preference")
        self.assertEqual(matches[0]["id"], preference["id"])
        updated = self.store.update(preference["id"], content="I prefer concise engineering answers.")
        self.assertIsNotNone(updated)
        self.assertTrue(self.store.delete(preference["id"]))
        self.assertIsNone(self.store.get(preference["id"]))

    def test_secret_like_values_are_not_persisted(self) -> None:
        with self.assertRaises(SensitiveMemoryError):
            self.store.create("api_key=sk-this-is-a-secret-value-123456789")
        self.assertEqual(self.store.list(), [])


class ConversationCompressionTests(unittest.TestCase):
    def test_overflow_is_compressed_without_changing_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "conversation.json"
            store = JSONMemory(path, history_limit=2)
            store.append("session", "user", "first message", "casual")
            store.append("session", "assistant", "first response", "casual")
            store.append("session", "user", "second message", "planning")
            self.assertEqual(len(store.get_history("session")), 2)
            self.assertIn("first message", store.get_summary("session") or "")
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("conversations", document)
            self.assertIn("summaries", document)

    def test_corrupt_existing_memory_fails_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "conversation.json"
            path.write_text("{not valid json", encoding="utf-8")
            store = JSONMemory(path, history_limit=2)
            with self.assertRaises(RuntimeError):
                store.append("session", "user", "do not overwrite")
            self.assertEqual(path.read_text(encoding="utf-8"), "{not valid json")


if __name__ == "__main__":
    unittest.main()
