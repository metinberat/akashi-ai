import tempfile
import unittest
from pathlib import Path

from app.files.service import FileIntelligenceService, FileValidationError


class FileIntelligenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.files = FileIntelligenceService(root / "uploads", root / "index.json", 1024)

    def test_validated_text_round_trip_uses_id_storage(self) -> None:
        record = self.files.save("../notes.md", "text/markdown", b"# Safe\nAKASHI")
        self.assertEqual(record["name"], "notes.md")
        self.assertEqual(self.files.get_text(record["id"]), "# Safe\nAKASHI")
        stored = list((Path(self.temporary.name) / "uploads").iterdir())
        self.assertEqual(len(stored), 1)
        self.assertNotIn("notes", stored[0].name)

    def test_binary_unsupported_and_oversized_files_are_rejected(self) -> None:
        with self.assertRaises(FileValidationError):
            self.files.save("malware.exe", "application/octet-stream", b"MZ")
        with self.assertRaises(FileValidationError):
            self.files.save("large.txt", "text/plain", b"x" * 1025)
        with self.assertRaises(FileValidationError):
            self.files.save("binary.txt", "text/plain", b"a\x00b")

    def test_invalid_ids_cannot_traverse_storage(self) -> None:
        with self.assertRaises(FileValidationError):
            self.files.get_text("../../outside")


if __name__ == "__main__":
    unittest.main()
