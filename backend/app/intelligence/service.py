"""MISS MINUTES discovery and relevance evaluation.

Remote text is parsed as inert source data. This service has no tool registry,
subprocess, package manager, source writer, or deployment access by design.
"""

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence
from urllib.parse import urljoin, urlsplit

import httpx

from app.intelligence.store import JSONIntelligenceStore


@dataclass(frozen=True)
class IntelligenceFeedSource:
    name: str
    url: str
    category: str
    subsystem: str
    source_kind: str = "official"


DEFAULT_FEEDS: Sequence[IntelligenceFeedSource] = (
    IntelligenceFeedSource("Ollama Releases", "https://github.com/ollama/ollama/releases.atom", "AI / Agents", "local_inference"),
    IntelligenceFeedSource("ComfyUI Releases", "https://github.com/Comfy-Org/ComfyUI/releases.atom", "AKASHI Watch", "image_generation"),
    IntelligenceFeedSource("whisper.cpp Releases", "https://github.com/ggml-org/whisper.cpp/releases.atom", "AKASHI Watch", "voice"),
    IntelligenceFeedSource("arXiv AI", "https://export.arxiv.org/rss/cs.AI", "Science", "research", "primary_research"),
    IntelligenceFeedSource("Python Insider", "https://blog.python.org/feeds/posts/default", "Technology", "backend"),
)


def _plain_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", html.unescape(value or ""))
    without_controls = "".join(character for character in without_tags if character >= " " or character in "\n\t")
    return " ".join(without_controls.split())[:4_000]


def _date(value: str) -> Optional[str]:
    clean = value.strip()
    if not clean:
        return None
    try:
        parsed = datetime.fromisoformat(clean.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(clean)
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


class IntelligenceService:
    def __init__(
        self,
        store: JSONIntelligenceStore,
        timeout_seconds: float = 20.0,
        feeds: Sequence[IntelligenceFeedSource] = DEFAULT_FEEDS,
    ) -> None:
        self.store = store
        self.timeout_seconds = timeout_seconds
        self.feeds = tuple(feeds)

    @staticmethod
    def _validate_feed(source: IntelligenceFeedSource) -> None:
        parsed = urlsplit(source.url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Intelligence feeds must be server-configured HTTPS URLs.")
        host = parsed.hostname.casefold()
        if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local"):
            raise ValueError("Private-network intelligence feeds are not allowed.")

    @staticmethod
    def _entries(xml_text: str, source: IntelligenceFeedSource) -> Iterable[Dict[str, Optional[str]]]:
        root = ET.fromstring(xml_text)
        for node in list(root.findall("{*}entry")) + list(root.findall(".//item")):
            title_node = node.find("{*}title") if node.tag.endswith("entry") else node.find("title")
            title = _plain_text(title_node.text if title_node is not None and title_node.text else "")
            link = ""
            for link_node in node.findall("{*}link"):
                candidate = link_node.attrib.get("href") or link_node.text or ""
                if candidate and link_node.attrib.get("rel", "alternate") in {"alternate", ""}:
                    link = urljoin(source.url, candidate.strip())
                    break
            if not link:
                rss_link = node.find("link")
                link = urljoin(source.url, (rss_link.text or "").strip()) if rss_link is not None else ""
            summary_node = next(
                (
                    candidate
                    for candidate in (
                        node.find("{*}summary"),
                        node.find("{*}content"),
                        node.find("description"),
                    )
                    if candidate is not None
                ),
                None,
            )
            summary = _plain_text(summary_node.text if summary_node is not None and summary_node.text else "")
            date_node = next(
                (
                    candidate
                    for candidate in (
                        node.find("{*}published"),
                        node.find("{*}updated"),
                        node.find("pubDate"),
                    )
                    if candidate is not None
                ),
                None,
            )
            published = _date(date_node.text if date_node is not None and date_node.text else "")
            if title and link.startswith("https://"):
                yield {"title": title, "url": link, "summary": summary, "publication_date": published}

    @staticmethod
    def evaluate(entry: Dict[str, Optional[str]], source: IntelligenceFeedSource) -> Dict[str, str]:
        searchable = f"{entry.get('title', '')} {entry.get('summary', '')}".casefold()
        security = any(term in searchable for term in ("security", "vulnerability", "cve", "exploit"))
        direct = source.subsystem in {"voice", "image_generation", "local_inference"} or source.category == "AKASHI Watch" or any(
            term in searchable
            for term in ("agent", "vision", "speech", "whisper", "ollama", "comfyui", "cuda", "inference", "tool calling")
        )
        relevance = "direct" if direct else "adjacent" if source.category in {"AI / Agents", "Technology"} else "general"
        if source.subsystem == "voice":
            benefit = "Potential STT latency, accuracy, or local-runtime improvement; benchmark before integration."
        elif source.subsystem == "image_generation":
            benefit = "Potential image workflow, performance, or compatibility improvement; test against current ComfyUI workflows."
        elif source.subsystem == "local_inference":
            benefit = "Potential local model runtime or GPU utilization improvement; compare on the RTX 4080 SUPER."
        else:
            benefit = "Relevant evidence for future architecture or product decisions; no automatic change is authorized."
        return {
            "why_it_matters": benefit,
            "akashi_relevance": relevance,
            "affected_subsystem": source.subsystem,
            "maturity": "official_release" if source.source_kind == "official" else "primary_research",
            "risk": "review" if security else "low" if source.source_kind == "official" else "medium",
            "migration_effort": "medium" if direct else "unknown",
            "expected_benefit": benefit,
            "confidence": "high" if source.source_kind in {"official", "primary_research"} else "medium",
            "priority": "critical" if security and direct else "important" if direct else "daily_brief" if relevance == "adjacent" else "background",
        }

    async def discover(
        self,
        categories: Optional[Sequence[str]] = None,
        per_feed: int = 4,
    ) -> Dict[str, Any]:
        selected = [feed for feed in self.feeds if not categories or feed.category in categories]
        created: List[Dict[str, Any]] = []
        merged = 0
        failures: List[Dict[str, str]] = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=45)
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            follow_redirects=False,
            headers={"User-Agent": "AkashiAI-MissMinutes/1.0 (personal intelligence monitor)"},
        ) as client:
            for feed in selected:
                self._validate_feed(feed)
                try:
                    response = await client.get(feed.url, headers={"Accept": "application/atom+xml, application/rss+xml, application/xml, text/xml"})
                    response.raise_for_status()
                    accepted = 0
                    for entry in self._entries(response.text[:2_000_000], feed):
                        publication = entry.get("publication_date")
                        if publication and datetime.fromisoformat(publication) < cutoff:
                            continue
                        evaluation = self.evaluate(entry, feed)
                        item, is_new = self.store.merge_discovery({
                            "title": entry["title"],
                            "category": feed.category,
                            "publication_date": publication,
                            "summary": entry.get("summary") or "No source summary was supplied.",
                            "source": {
                                "url": entry["url"],
                                "title": entry["title"],
                                "provider": feed.name,
                                "publication_date": publication,
                            },
                            **evaluation,
                        })
                        if is_new:
                            created.append(item)
                        else:
                            merged += 1
                        accepted += 1
                        if accepted >= max(1, min(per_feed, 10)):
                            break
                except (httpx.HTTPError, ET.ParseError, ValueError) as exc:
                    failures.append({"source": feed.name, "error": type(exc).__name__})
        return {
            "status": "completed" if not failures else "partial" if created or merged else "failed",
            "sources_checked": len(selected),
            "created": len(created),
            "merged": merged,
            "failures": failures,
            "items": created,
        }

    def create_daily_brief(self, lookback_days: int = 7) -> Dict[str, Any]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, min(lookback_days, 30)))
        recent = []
        for item in self.store.list_items(limit=500):
            timestamp = item.get("publication_date") or item.get("discovered_at")
            try:
                if datetime.fromisoformat(timestamp) >= cutoff and item.get("status") != "dismissed":
                    recent.append(item)
            except (TypeError, ValueError):
                continue
        order = {"critical": 0, "important": 1, "daily_brief": 2, "background": 3}
        recent.sort(key=lambda item: (order.get(item.get("priority"), 4), item.get("publication_date") or ""))
        selected = recent[:12]
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for item in selected:
            groups.setdefault(item["category"], []).append(item)
        brief = {
            "title": "AKASHI DAILY INTELLIGENCE",
            "status": "completed",
            "lookback_days": lookback_days,
            "item_count": len(selected),
            "groups": groups,
            "empty_reason": None if selected else "No verified intelligence items are available for this period.",
        }
        return self.store.save_brief(brief)
