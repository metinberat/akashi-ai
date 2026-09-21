import re
from dataclasses import asdict
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional, Sequence
from urllib.parse import urldefrag

from app.research.base import ResearchProvider, ResearchSource

ResearchMode = Literal["normal", "deep"]
ProgressCallback = Callable[[str, Dict[str, Any]], Awaitable[None]]
SynthesisCallback = Callable[[str, Sequence[ResearchSource]], Awaitable[str]]


class ResearchService:
    """Multi-query research orchestration with explicit, real source metadata."""

    def __init__(
        self,
        provider: ResearchProvider,
        synthesizer: Optional[SynthesisCallback] = None,
    ) -> None:
        self.provider = provider
        self.synthesizer = synthesizer

    @staticmethod
    def formulate_queries(question: str, mode: ResearchMode) -> List[str]:
        clean = " ".join(question.split()).strip()
        if mode == "normal":
            return [clean]
        core = re.sub(r"[?!.]+$", "", clean)
        variants = [clean, f"{core} overview", f"{core} evidence recent developments"]
        return list(dict.fromkeys(item for item in variants if item))

    async def run(
        self,
        question: str,
        mode: ResearchMode = "normal",
        progress: Optional[ProgressCallback] = None,
    ) -> Dict[str, Any]:
        clean = question.strip()
        if not clean:
            raise ValueError("Research question cannot be empty.")

        async def emit(state: str, payload: Optional[Dict[str, Any]] = None) -> None:
            if progress is not None:
                await progress(state, payload or {})

        await emit("planning", {"mode": mode})
        queries = self.formulate_queries(clean, mode)
        collected: List[ResearchSource] = []
        try:
            for index, query in enumerate(queries):
                await emit("searching", {"query": query, "index": index})
                collected.extend(await self.provider.search(query, 5 if mode == "deep" else 6))
            await emit("reading", {"source_count": len(collected)})
            deduplicated: Dict[str, ResearchSource] = {}
            for source in collected:
                key = urldefrag(source.url)[0].rstrip("/").casefold()
                existing = deduplicated.get(key)
                if existing is None or source.relevance > existing.relevance:
                    deduplicated[key] = source
            sources = sorted(
                deduplicated.values(),
                key=lambda item: item.relevance,
                reverse=True,
            )[: (15 if mode == "deep" else 6)]
            await emit("synthesizing", {"source_count": len(sources)})
            findings = [
                {"title": item.title, "finding": item.snippet, "source_url": item.url}
                for item in sources
                if item.snippet
            ]
            summary = (
                f"Collected {len(sources)} distinct source(s). "
                "The findings below are source extracts; use the linked sources for verification."
            )
            synthesis_status = "source-only"
            if sources and self.synthesizer is not None:
                try:
                    summary = await self.synthesizer(clean, sources)
                    synthesis_status = "completed"
                except Exception:
                    synthesis_status = "unavailable"
            result = {
                "question": clean,
                "mode": mode,
                "provider": self.provider.name,
                "queries": queries,
                "status": "completed",
                "summary": summary,
                "synthesis_status": synthesis_status,
                "findings": findings,
                "sources": [asdict(item) for item in sources],
            }
            await emit("completed", {"source_count": len(sources)})
            return result
        except Exception as exc:
            await emit("failed", {"error": type(exc).__name__})
            raise
