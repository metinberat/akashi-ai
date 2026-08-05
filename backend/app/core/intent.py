import re
import unicodedata
from typing import Dict, Literal, Sequence, Tuple

Intent = Literal["study", "code", "research", "casual", "planning", "unknown"]

INTENT_KEYWORDS: Dict[Intent, Sequence[str]] = {
    "study": (
        "study", "studying", "learn", "lesson", "exam", "quiz", "practice",
        "homework", "teach", "explain", "question solving", "take notes",
        "summary", "physics", "chemistry", "biology", "math", "mathematics",
        "literature", "history", "geography", "philosophy",
        "ders", "ders çalış", "çalıştır", "konu", "sınav", "test", "soru", "çöz",
        "anlat", "öğren", "fizik", "kimya", "biyoloji", "matematik",
        "edebiyat", "tarih", "coğrafya", "felsefe", "elektrik alan",
        "parabol", "molarite", "sindirim", "özet", "not çıkar",
    ),
    "code": (
        "code", "coding", "python", "javascript", "typescript", "fastapi",
        "react", "nextjs", "bug", "error", "traceback", "terminal", "endpoint",
        "api", "function", "class", "variable", "import", "install", "package",
        "backend", "frontend", "repository",
    ),
    "research": (
        "research", "investigate", "compare", "sources", "evidence", "paper",
        "literature review", "analyze", "araştır", "kaynak", "makale",
    ),
    "planning": (
        "plan", "roadmap", "schedule", "strategy", "steps", "organize",
        "timeline", "goal", "planla", "takvim", "strateji",
    ),
    "casual": (
        "hello", "hi", "hey", "thanks", "thank you", "how are you", "chat",
        "selam", "merhaba", "teşekkür", "nasılsın",
    ),
    "unknown": (),
}

# These signals take precedence over code terms because they clearly establish
# an educational context. Turkish stems intentionally match suffixes such as
# "çalıştır", "soruları", and "çözmek".
STUDY_OVERRIDE_KEYWORDS: Tuple[str, ...] = (
    "study", "studying", "lesson", "exam", "homework", "question solving",
    "physics", "chemistry", "biology", "math", "mathematics",
    "literature", "history", "geography", "philosophy",
    "ders", "ders çalış", "çalıştır", "sınav", "soru", "çöz", "öğren",
    "fizik", "kimya", "biyoloji", "matematik", "edebiyat", "tarih",
    "coğrafya", "felsefe", "elektrik alan", "parabol", "molarite", "sindirim",
)

PREFIX_KEYWORDS = {
    "ders", "ders çalış", "çalıştır", "konu", "sınav", "soru", "çöz", "anlat",
    "öğren", "fizik", "kimya", "biyoloji", "matematik", "edebiyat",
    "coğrafya", "felsefe", "parabol", "molarite", "sindirim", "özet",
    "araştır", "kaynak", "makale", "planla", "takvim", "strateji",
}

INTENT_PRIORITY: Tuple[Intent, ...] = (
    "study", "code", "research", "planning", "casual",
)


def _normalize(message: str) -> str:
    normalized = unicodedata.normalize("NFKC", message).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def _contains_keyword(message: str, keyword: str) -> bool:
    escaped = re.escape(keyword)
    if keyword in PREFIX_KEYWORDS:
        pattern = rf"(?<!\w){escaped}\w*"
    else:
        pattern = rf"(?<!\w){escaped}(?!\w)"
    return re.search(pattern, message, flags=re.UNICODE) is not None


def analyze_intent(message: str) -> Intent:
    """Classify Turkish and English messages using phrase-aware keyword scores."""
    normalized = _normalize(message)
    if not normalized:
        return "unknown"

    if any(
        _contains_keyword(normalized, keyword)
        for keyword in STUDY_OVERRIDE_KEYWORDS
    ):
        return "study"

    scores = {
        intent: sum(
            _contains_keyword(normalized, keyword)
            for keyword in INTENT_KEYWORDS[intent]
        )
        for intent in INTENT_PRIORITY
    }
    highest_score = max(scores.values(), default=0)
    if highest_score == 0:
        return "unknown"

    return next(
        intent for intent in INTENT_PRIORITY if scores[intent] == highest_score
    )
