import unittest

from app.research.base import ResearchProvider, ResearchSource
from app.research.service import ResearchService


class FakeResearchProvider(ResearchProvider):
    name = "test"

    async def search(self, query: str, limit: int = 5) -> list[ResearchSource]:
        return [
            ResearchSource("Source", "https://example.test/article#section", f"Finding for {query}", self.name, 0.8),
            ResearchSource("Duplicate", "https://example.test/article", "Duplicate", self.name, 0.4),
        ]


class ResearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_deep_research_is_multi_query_and_deduplicates_sources(self) -> None:
        service = ResearchService(FakeResearchProvider())
        states = []

        async def progress(state: str, payload: dict) -> None:
            states.append(state)

        result = await service.run("Akashi architecture?", "deep", progress)
        self.assertEqual(len(result["queries"]), 3)
        self.assertEqual(len(result["sources"]), 1)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(states[0], "planning")
        self.assertEqual(states[-1], "completed")


if __name__ == "__main__":
    unittest.main()
