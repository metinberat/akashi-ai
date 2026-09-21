from typing import Sequence

from app.core.intent import Intent
from app.memory.base import MemoryMessage
from app.providers.base import AIProvider


class MockProvider(AIProvider):
    """Local Akashi-style provider used without credentials."""

    name = "mock"

    async def generate(
        self,
        message: str,
        system_prompt: str,
        history: Sequence[MemoryMessage],
        intent: Intent,
    ) -> str:
        turkish = any(char in message.casefold() for char in "çğıöşü") or any(word in message.casefold().split() for word in ("merhaba", "selam", "ders", "bana"))
        if turkish:
            responses_tr = {
                "study": "Çalışma planı:\n1. Konunun temel kuralını belirle.\n2. Bir örneği adım adım çöz.\n3. Üç soruyla bilgini sınayıp hataları not et.\n4. Kısa bir özet çıkar.",
                "code": "Önce hatayı yeniden üret. Beklenen sonucu, ilgili kodu ve hata çıktısını gönder. Sonra en küçük bileşeni izole edip düzeltmeyi test et.",
                "research": "Araştırma çalışma alanını kullan. Kaynaklar alınmadan bulgu veya doğrulama iddiasında bulunamam.",
                "planning": "Hedefi ve son tarihi belirle. İşi bağımlılıklarına göre sırala. İlk adım, ölçülebilir en küçük çıktı olsun.",
                "casual": "Buradayım. Hangi konuyu ele alıyoruz?",
                "unknown": "Hedefi netleştir: bir açıklama, karar, plan veya kod incelemesi mi gerekiyor?",
            }
            return responses_tr[intent] + "\n\nMOCK · Bağlantı testi yanıtı; gerçek model çıkarımı değil."
        previous_turns = len(history) // 2
        continuity = (
            f"\n\nContext: I found {previous_turns} relevant earlier "
            "conversation turn(s)."
            if previous_turns
            else ""
        )
        responses = {
            "study": (
                "Study plan:\n\n"
                "1. Define the exact learning goal.\n"
                "2. Review the core idea in plain language.\n"
                "3. Work through one guided example.\n"
                "4. Test recall with three short questions.\n"
                "5. Finish with a brief summary and next step."
            ),
            "code": (
                "Engineering approach:\n\n"
                "Approach:\n"
                "- Clarify the expected input, output, and constraints.\n"
                "- Isolate the smallest testable component.\n"
                "- Implement it behind a clean interface.\n"
                "- Verify the happy path, edge cases, and failure behavior.\n\n"
                "Send the relevant code and error output."
            ),
            "research": (
                "Use the Research workspace to collect evidence. No sources have been retrieved in this chat.\n\n"
                "- Frame a precise question.\n"
                "- Separate primary evidence from commentary.\n"
                "- Compare credible sources and note disagreements.\n"
                "- Record uncertainty, dates, and assumptions.\n"
                "- Synthesize findings into a concise conclusion."
            ),
            "planning": (
                "Execution plan:\n\n"
                "1. Define the outcome and deadline.\n"
                "2. Split it into milestones.\n"
                "3. Choose the smallest useful first action.\n"
                "4. Identify risks and dependencies.\n"
                "5. Set a review point and adjust."
            ),
            "casual": (
                "Ready. What are we working on?"
            ),
            "unknown": (
                "Define the outcome: explanation, decision, plan or code review."
            ),
        }
        return responses[intent] + continuity + "\n\nMOCK · Connectivity response, not model inference."
