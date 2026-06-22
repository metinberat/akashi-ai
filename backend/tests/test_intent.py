import unittest

from app.core.intent import analyze_intent


class IntentAnalyzerTests(unittest.TestCase):
    def test_turkish_physics_study_message(self) -> None:
        message = "Bugün bana fizik çalıştır, elektrik alan çizgilerini anlamam lazım."
        self.assertEqual(analyze_intent(message), "study")

    def test_turkish_exam_and_question_solving(self) -> None:
        self.assertEqual(
            analyze_intent("Matematik sınavı için parabol soruları çözelim."),
            "study",
        )

    def test_turkish_suffixes(self) -> None:
        self.assertEqual(
            analyze_intent("Bu konuyu anlatır mısın, sonra soruları çözeriz."),
            "study",
        )

    def test_english_school_subject_overrides_code_word(self) -> None:
        self.assertEqual(
            analyze_intent("Help me study physics with a Python simulation."),
            "study",
        )

    def test_code_message(self) -> None:
        self.assertEqual(
            analyze_intent("Debug this FastAPI endpoint traceback."),
            "code",
        )

    def test_short_code_keyword_does_not_match_inside_word(self) -> None:
        self.assertNotEqual(analyze_intent("Bu akşam nasılsın?"), "code")


if __name__ == "__main__":
    unittest.main()
