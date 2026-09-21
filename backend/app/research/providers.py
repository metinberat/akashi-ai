"""Real, swappable research providers used by the ABSOLUTE Engine."""

from typing import Any, Dict, List

import httpx

from app.research.base import ResearchProvider, ResearchSource


class WikipediaResearchProvider(ResearchProvider):
    name = "wikipedia"

    def __init__(self, language: str = "en", timeout_seconds: float = 20.0) -> None:
        self._base_url = f"https://{language}.wikipedia.org/w/api.php"
        self._timeout = timeout_seconds

    async def search(self, query: str, limit: int = 5) -> List[ResearchSource]:
        bounded_limit = max(1, min(limit, 10))
        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
            headers={"User-Agent": "AkashiAI-PreAstra/0.4 (personal research assistant)"},
        ) as client:
            response = await client.get(
                self._base_url,
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "srlimit": bounded_limit,
                    "format": "json",
                    "utf8": "1",
                },
            )
            response.raise_for_status()
            results = response.json().get("query", {}).get("search", [])
            page_ids = [str(item.get("pageid")) for item in results if item.get("pageid")]
            extracts: Dict[str, Dict[str, Any]] = {}
            if page_ids:
                detail = await client.get(
                    self._base_url,
                    params={
                        "action": "query",
                        "pageids": "|".join(page_ids),
                        "prop": "extracts|info",
                        "exintro": "1",
                        "explaintext": "1",
                        "inprop": "url",
                        "format": "json",
                        "utf8": "1",
                    },
                )
                detail.raise_for_status()
                extracts = detail.json().get("query", {}).get("pages", {})

        sources: List[ResearchSource] = []
        for index, item in enumerate(results):
            page = extracts.get(str(item.get("pageid")), {})
            snippet = " ".join(
                str(page.get("extract") or item.get("snippet") or "").split()
            )
            sources.append(
                ResearchSource(
                    title=str(item.get("title") or page.get("title") or "Untitled"),
                    url=str(page.get("fullurl") or ""),
                    snippet=snippet[:2_000],
                    provider=self.name,
                    relevance=max(0.25, 1.0 - index * 0.08),
                )
            )
        return [source for source in sources if source.url]


class SearxNGResearchProvider(ResearchProvider):
    name = "searxng"

    def __init__(self, base_url: str, timeout_seconds: float = 20.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    async def search(self, query: str, limit: int = 5) -> List[ResearchSource]:
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            response = await client.get(
                f"{self._base_url}/search",
                params={"q": query, "format": "json", "safesearch": "1"},
            )
            response.raise_for_status()
            results = response.json().get("results", [])
        sources: List[ResearchSource] = []
        for index, item in enumerate(results[: max(1, min(limit, 10))]):
            url = str(item.get("url") or "")
            if not url.startswith(("https://", "http://")):
                continue
            raw_score = item.get("score")
            score = float(raw_score) if isinstance(raw_score, (int, float)) else 1.0 - index * 0.08
            sources.append(
                ResearchSource(
                    title=str(item.get("title") or url),
                    url=url,
                    snippet=" ".join(str(item.get("content") or "").split())[:2_000],
                    provider=self.name,
                    relevance=max(0.0, min(score, 1.0)),
                )
            )
        return sources


class DuckDuckGoResearchProvider(ResearchProvider):
    """Instant Answer topic evidence, not general web search or full-page reading."""
    name = "duckduckgo-topics"

    def __init__(self, timeout_seconds: float = 20.0) -> None:
        self._timeout = timeout_seconds

    async def search(self, query: str, limit: int = 5) -> List[ResearchSource]:
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False) as client:
            response = await client.get("https://api.duckduckgo.com/", params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"})
            response.raise_for_status()
            data = response.json()
        sources = []
        if data.get("AbstractURL") and data.get("AbstractText"):
            sources.append(ResearchSource(str(data.get("Heading") or query), data["AbstractURL"], data["AbstractText"][:2000], self.name, 1.0))
        related = []
        for item in data.get("RelatedTopics", []):
            related.extend(item.get("Topics", [item]))
        for item in related:
            url, text = str(item.get("FirstURL") or ""), str(item.get("Text") or "")
            if url.startswith("https://") and text:
                sources.append(ResearchSource(text.split(" - ")[0][:150], url, text[:2000], self.name, 0.5))
        return sources[:max(1, min(limit, 10))]
