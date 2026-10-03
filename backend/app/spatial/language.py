"""Natural language → Spatial Lab requests.

Two interpreters produce the *same* output: a short list of public request
dicts (``requests.py``), which then pass the same validation, reference
resolution, compilation and reducer checks as gestures and UI input.

* ``RuleInterpreter`` — deterministic, local, Turkish and English. It needs no
  model and is always available.
* ``ModelInterpreter`` — optional fallback through AKASHI's model router (for
  example local Ollama qwen3:8b). The model only proposes JSON requests; any
  output that fails schema validation is discarded. It never executes anything.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydantic import ValidationError

from app.live.actions.base import is_turkish, normalize_text
from app.spatial.compiler import CLIP_CONCEPTS
from app.spatial.requests import REQUEST_LIST_ADAPTER

TURKISH_HINTS = re.compile(r"\b(sec|secili|buyut|kucult|dondur|cevir|goster|gizle|oynat|durdur|yukle|getir|ortaya|"
                           r"sifirla|geri al|yinele|tasi|koy|sag|sol|elime|iskelet|surum|karakter|onu|bunu|sunu|"
                           r"soldaki|sagdaki|derece|incele|biraz|kaldir|sil)\b")
GENERIC_WORDS = {"character", "object", "model", "karakter", "nesne", "the", "this", "that", "form", "version",
                 "surum", "latest", "calibration", "synthetic", "block", "uploaded", "glb"}


@dataclass
class Interpretation:
    requests: List[Dict[str, Any]]
    source: str
    language: str
    rule: str = ""
    notes: List[str] = field(default_factory=list)


def _clean(text: str) -> str:
    value = normalize_text(text)
    value = re.sub(r"[^\w\s%.,°-]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _cut(text: str, pattern: str) -> Tuple[Optional[re.Match], str]:
    match = re.search(pattern, text)
    if not match:
        return None, text
    return match, (text[:match.start()] + " " + text[match.end():]).strip()


def _number(raw: str) -> float:
    return float(raw.replace(",", "."))


ANCHOR = r"\b(?:to |in |into |onto |toward |towards )?(?:my |the )?(right|left) hand\b|\b(sag|sol) el(?:ime|imde|imin|ine|e|i)?\b"
REFERENCES: List[Tuple[str, Dict[str, Any]]] = [
    (r"\b(?:the )?(?:currently )?selected(?: one| character| object)?\b|\bsecili(?: olan| karakter| nesne)?\b|\bsecilen\b", {"ref": "selected"}),
    (r"\b(?:the )?one i (?:just )?moved\b|\b(?:just|last) moved\b|\bmoved last\b|\baz once tasidigim\b|\bson tasidigim\b", {"ref": "last_moved"}),
    (r"\b(?:the )?(?:one|character|object) on the left\b|\bon the left\b|\b(?:the )?left(?:most)? (?:one|character|object)\b|\b(?:en )?soldaki\b|\bsol taraftaki\b", {"ref": "leftmost"}),
    (r"\b(?:the )?(?:one|character|object) on the right\b|\bon the right\b|\b(?:the )?right(?:most)? (?:one|character|object)\b|\b(?:en )?sagdaki\b|\bsag taraftaki\b", {"ref": "rightmost"}),
    (r"\bthe (?:larger|bigger|largest|biggest)(?: one| character| object)?\b|\b(?:daha |en )?buyuk olan(?: karakter)?\b|\ben buyuk(?: karakter)?\b", {"ref": "largest"}),
    (r"\bthe (?:smaller|smallest)(?: one| character| object)?\b|\b(?:daha |en )?kucuk olan(?: karakter)?\b|\ben kucuk(?: karakter)?\b", {"ref": "smallest"}),
    (r"\b(?:the )?(?:latest|newest) version\b|\b(?:en )?(?:son|yeni) surum(?:u)?\b", {"ref": "latest_version"}),
    (r"\b(?:my|the) form (?:character|model)\b|\bform karakter(?:im|i)?\b", {"ref": "form"}),
]
DIRECTIONS = [
    (r"\b(?:to the )?left\b|\bsola\b", (-1.0, 0.0, 0.0), ("left", "sola")),
    (r"\b(?:to the )?right\b|\bsaga\b", (1.0, 0.0, 0.0), ("right", "saga")),
    (r"\bup(?:ward)?\b|\byukari\b", (0.0, 1.0, 0.0), ("up", "yukari")),
    (r"\bdown(?:ward)?\b|\basagi\b", (0.0, -1.0, 0.0), ("down", "asagi")),
    (r"\b(?:forward|closer|toward me)\b|\bileri\b|\byaklastir\b", (0.0, 0.0, 1.0), ("forward", "ileri")),
    (r"\b(?:backward|back|away)\b|\buzaklastir\b|\bgeriye\b", (0.0, 0.0, -1.0), ("back", "geri")),
]
HIDE = r"\b(hide|hidden|turn off|disable|off|remove the|gizle|kapat|sakla|kaldir)\b"
SHOW = r"\b(show|display|reveal|turn on|enable|on|unhide|goster|ac|gorunur)\b"


class RuleInterpreter:
    source = "rules"

    def interpret(self, text: str, summary: Optional[Dict[str, Any]] = None) -> Optional[Interpretation]:
        if not isinstance(text, str) or not text.strip() or len(text) > 500:
            return None
        original = text
        t = _clean(text)
        language = "tr" if is_turkish(original) or TURKISH_HINTS.search(t) else "en"
        anchor_match, rest = _cut(t, ANCHOR)
        anchor = None
        if anchor_match:
            side = anchor_match.group(1) or anchor_match.group(2)
            anchor = "right_hand" if side in {"right", "sag"} else "left_hand"
        ref, rest = self._reference(rest, summary)
        found = self._action(rest, t, ref, anchor, summary)
        if found is None:
            return None
        rule, requests = found
        return Interpretation(requests=requests, source=self.source, language=language, rule=rule)

    # References -------------------------------------------------------------------
    def _reference(self, text: str, summary: Optional[Dict[str, Any]]) -> Tuple[Dict[str, Any], str]:
        for pattern, ref in REFERENCES:
            match, rest = _cut(text, pattern)
            if match:
                return dict(ref), rest
        for obj in (summary or {}).get("objects", []):
            label = _clean(obj.get("label", ""))
            words = [w for w in re.findall(r"[a-z0-9]{4,}", label) if w not in GENERIC_WORDS]
            if label and label in text:
                return {"ref": "label", "label": obj["label"]}, text.replace(label, " ")
            for word in words:
                if re.search(rf"\b{re.escape(word)}\b", text):
                    return {"ref": "label", "label": word}, text
        return {"ref": "deictic"}, text

    # Actions ----------------------------------------------------------------------
    def _action(self, t: str, full: str, ref: Dict[str, Any], anchor: Optional[str],
                summary: Optional[Dict[str, Any]]) -> Optional[Tuple[str, List[Dict[str, Any]]]]:
        def has(pattern: str, value: str = t) -> bool:
            return re.search(pattern, value) is not None

        hide = has(HIDE)
        if has(r"\b(undo|undo that|geri al|geri alin|son islemi geri)\b"):
            return "undo", [{"type": "history.undo"}]
        if has(r"\b(redo|yinele|ileri al|tekrar uygula)\b"):
            return "redo", [{"type": "history.redo"}]
        if has(r"\b(calibration|kalibrasyon)\b") and has(r"\b(load|add|open|bring|show|place|yukle|ekle|getir|ac|koy|goster)\b"):
            return "load_fixture", [{"type": "scene.add_asset", "fixture": "calibration"}]
        version = self._version(full)
        form_word = has(r"\bform\b", full)
        loading = has(r"\b(load|open|bring|add|import|show|put|yukle|getir|ac|ekle|goster|koy)\b")
        switching = has(r"\b(switch|change|go to|use|gec|degistir|kullan)\b")
        has_form_object = any(o.get("source") == "form" for o in (summary or {}).get("objects", []))
        if (form_word and (loading or switching or version)) or (version and (switching or loading)):
            selector = version or "latest"
            target_ref = ref if ref.get("ref") not in {"deictic", "latest_version"} else {"ref": "form"}
            if has_form_object and (switching or version or ref.get("ref") != "deictic" or not has(r"\b(add|another|new|ekle|yeni|bir tane daha)\b")):
                return "form_version", [{"type": "object.version", "target": target_ref, "version": selector}]
            return "form_load", [{"type": "scene.add_asset", "form": {"version": selector}}]
        if has(r"\b(remove|delete|discard|sil|kaldir|cikar)\b") and not has(r"\b(hud|rig|skeleton|iskelet|vfx|efekt|selection|secim)\b"):
            return "remove", [{"type": "scene.remove", "target": ref}]
        if has(r"\b(rig|skeleton|bones|iskelet|iskeleti|kemik|kemikleri)\b"):
            return "rig", [{"type": "object.display", "target": ref, "skeleton": not hide}]
        if has(r"\bhud\b"):
            if has(r"\b(its|his|her|character|karakter|karakterin|rings?|halka|halkalari|hudunu)\b") or ref.get("ref") != "deictic":
                return "form_hud", [{"type": "object.display", "target": ref, "form_hud": not hide}]
            return "view_hud", [{"type": "view.set", "hud_visible": not hide}]
        if has(r"\b(vfx|effects?|efekt|efektler|efektleri)\b"):
            return "vfx", [{"type": "view.set", "vfx_visible": not hide}]
        if has(r"\b(bounds|bounding box|sinir kutusu)\b"):
            return "bounds", [{"type": "object.display", "target": ref, "bounds": not hide}]
        clip = self._clip(t)
        if has(r"\b(pause|freeze|duraklat|durdur)\b") and (clip or has(r"\b(anim|animation|animasyon|animasyonu|motion|hareket)\w*\b")):
            return "pause", [{"type": "animation.control", "target": ref, "action": "pause"}]
        if has(r"\bstop\b") and has(r"\b(anim|animation|motion)\w*\b"):
            return "stop", [{"type": "animation.control", "target": ref, "action": "stop"}]
        if has(r"\b(play|start|run|animate|resume|oynat|baslat|calistir|devam)\b") and (clip or has(r"\b(anim\w*|motion|hareket\w*|clip|klip)\b")):
            request = {"type": "animation.control", "target": ref, "action": "play"}
            if clip:
                request["clip"] = clip
            return "play", [request]
        if anchor and has(r"\b(move|bring|put|place|send|attach|snap|tasi|getir|koy|gonder|al|yerlestir)\b"):
            return "to_anchor", [{"type": "object.transform", "target": ref, "mode": "to_anchor", "anchor": anchor}]
        if has(r"\b(center|centre|middle|ortala|ortaya|merkeze|ortada)\b"):
            return "center", [{"type": "object.transform", "target": ref, "mode": "center"}]
        if has(r"\b(reset|sifirla|varsayilana)\b"):
            return "reset", [{"type": "object.transform", "target": ref, "mode": "reset"}]
        if has(r"\b(rotate|turn|spin|dondur|cevir|dondurun)\b"):
            degrees = 45.0
            number = re.search(r"(-?\d+(?:[.,]\d+)?)\s*(?:degrees?|deg|°|derece)", t)
            if number:
                degrees = _number(number.group(1))
            elif has(r"\b(around|arkasini|arkaya|180)\b"):
                degrees = 180.0
            elif has(r"\b(quarter|ceyrek)\b"):
                degrees = 90.0
            if has(r"\b(clockwise|right|saga|saat yonunde)\b") and not has(r"\bcounter ?clockwise\b"):
                degrees = -abs(degrees)
            return "rotate", [{"type": "object.transform", "target": ref, "mode": "rotate", "axis": "y", "degrees": degrees}]
        bigger = has(r"\b(bigger|larger|enlarge|grow|scale up|increase|buyut|buyusun|buyult|buyuk yap|genislet)\b|\bas (?:big|large)\b|\bdouble (?:the |its )?size\b")
        smaller = has(r"\b(smaller|shrink|reduce|scale down|decrease|kucult|kucuk yap|daralt)\b")
        if bigger or smaller:
            factor = 1.25 if bigger else 0.8
            multiplier = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:x|times|kat)\b", t)
            if multiplier and _number(multiplier.group(1)) > 0:
                value = _number(multiplier.group(1))
                factor = value if bigger else 1 / value
            elif has(r"\b(twice|double|iki kat)\b"):
                factor = 2.0 if bigger else 0.5
            elif has(r"\b(half|yarisi|yariya)\b"):
                factor = 0.5
            elif has(r"\b(a bit|a little|slightly|biraz|azicik)\b"):
                factor = 1.1 if bigger else 0.9
            return "scale", [{"type": "object.transform", "target": ref, "mode": "scale", "factor": factor}]
        if has(r"\b(move|shift|push|slide|nudge|tasi|kaydir|gotur)\b"):
            for pattern, vector, _names in DIRECTIONS:
                if has(pattern):
                    distance = 0.25
                    amount = re.search(r"(\d+(?:[.,]\d+)?)\s*(cm|centimeters?|santim|m|meters?|metres?|metre)\b", t)
                    if amount:
                        distance = _number(amount.group(1)) / (100 if amount.group(2).startswith(("c", "s")) else 1)
                    distance = min(max(distance, 0.01), 4.0)
                    return "translate", [{"type": "object.transform", "target": ref, "mode": "translate",
                                          "delta": [round(v * distance, 4) for v in vector]}]
        if has(r"\b(deselect|unselect|clear (?:the )?selection|secimi (?:kaldir|temizle|birak))\b"):
            return "deselect", [{"type": "selection.select"}]
        if has(r"\b(select|choose|pick|focus on|sec)\b"):
            return "select", [{"type": "selection.select", "target": ref}]
        if has(r"\b(inspect|details?|metadata|info|information|properties|incele|detay\w*|bilgi\w*|ozellik\w*)\b"):
            return "inspect", [{"type": "view.inspect", "target": ref}]
        rename = re.search(r"\b(?:rename (?:it|this|that)? ?to|call it|name it)\s+(.{1,60})$", t)
        if rename:
            return "rename", [{"type": "object.rename", "target": ref, "label": rename.group(1).strip().title()}]
        if hide and not has(r"\b(hud|vfx)\b"):
            return "hide", [{"type": "object.visibility", "target": ref, "visible": False}]
        if has(SHOW) and has(r"\b(it|again|back|tekrar|onu|bunu|karakter\w*|character|object)\b"):
            return "show", [{"type": "object.visibility", "target": ref, "visible": True}]
        return None

    @staticmethod
    def _clip(text: str) -> Optional[str]:
        quoted = re.search(r"['\"]([^'\"]{1,60})['\"]", text)
        if quoted:
            return quoted.group(1)
        for words in CLIP_CONCEPTS.values():
            for word in words:
                if re.search(rf"\b{word}\w*", text):
                    return word
        named = re.search(r"\b([a-z0-9_-]{3,40}) (?:animation|animasyon\w*|clip|klip\w*)\b", text)
        if named and named.group(1) not in {"the", "this", "that", "an", "bir", "its", "play", "oynat"}:
            return named.group(1)
        return None

    @staticmethod
    def _version(text: str) -> Optional[str]:
        if re.search(r"\b(latest|newest|most recent|en son|en yeni|son)\b", text):
            return "latest"
        if re.search(r"\b(best|pinned|en iyi)\b", text):
            return "best"
        if re.search(r"\b(previous|older|onceki|eski)\b", text) and re.search(r"\b(version|surum\w*|v)\b", text):
            return "previous"
        if re.search(r"\b(next|newer|sonraki)\b", text) and re.search(r"\b(version|surum\w*|v)\b", text):
            return "next"
        label = re.search(r"\bv ?0*(\d{1,3})\b|\bversion (\d{1,3})\b|\bsurum (\d{1,3})\b|\b(\d{1,3})\. surum\w*\b", text)
        if label:
            return "V" + next(g for g in label.groups() if g).zfill(2)
        return None


SYSTEM_PROMPT = """You convert one Spatial Lab instruction into JSON. Reply with JSON only:
{"requests": [ ... ]}
Each request is one of:
{"type":"object.transform","target":REF,"mode":"translate","delta":[x,y,z]}   metres, +x right, +y up, +z toward the viewer
{"type":"object.transform","target":REF,"mode":"rotate","axis":"y","degrees":N}
{"type":"object.transform","target":REF,"mode":"scale","factor":F}
{"type":"object.transform","target":REF,"mode":"center"|"reset"}
{"type":"object.transform","target":REF,"mode":"to_anchor","anchor":"left_hand"|"right_hand"}
{"type":"object.display","target":REF,"skeleton":true|false}
{"type":"object.display","target":REF,"form_hud":true|false}
{"type":"view.set","hud_visible":true|false} or {"type":"view.set","vfx_visible":true|false}
{"type":"animation.control","target":REF,"action":"play"|"pause"|"stop","clip":"name"}
{"type":"object.version","target":REF,"version":"latest"|"best"|"previous"|"next"|"V03"}
{"type":"scene.add_asset","form":{"version":"latest"}}
{"type":"selection.select","target":REF} {"type":"view.inspect","target":REF}
{"type":"object.visibility","target":REF,"visible":true|false}
{"type":"history.undo"} {"type":"history.redo"}
REF is {"id":"obj-..."} for a listed object or {"ref":"selected"|"deictic"|"leftmost"|"rightmost"|"largest"|"smallest"|"form"|"latest_version"|"last_moved"}.
If the instruction is not a scene instruction or is unclear, reply {"requests": []}. Never invent object ids."""


class ModelInterpreter:
    source = "model"

    def __init__(self, provider: Callable[[], Any], timeout: float = 25.0) -> None:
        self.provider = provider
        self.timeout = timeout

    async def interpret(self, text: str, summary: Dict[str, Any]) -> Optional[Interpretation]:
        try:
            provider = self.provider()
        except Exception:
            return None
        if provider is None or getattr(provider, "name", "") == "mock":
            return None
        message = "Scene:\n" + json.dumps(summary, ensure_ascii=False)[:6000] + "\n\nInstruction:\n" + text[:500]
        try:
            raw = await asyncio.wait_for(provider.generate(message=message, system_prompt=SYSTEM_PROMPT, history=[], intent="unknown"), self.timeout)
        except Exception:
            return None
        requests = parse_model_output(raw, summary)
        if not requests:
            return None
        return Interpretation(requests=requests, source=f"model:{getattr(provider, 'name', 'unknown')}",
                              language="tr" if is_turkish(text) else "en", rule="model")


def parse_model_output(raw: Any, summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(raw, str):
        return []
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        value = json.loads(text[start:end + 1])
        requests = value.get("requests") if isinstance(value, dict) else None
        if not isinstance(requests, list) or not 1 <= len(requests) <= 3:
            return []
        parsed = REQUEST_LIST_ADAPTER.validate_python(requests)
    except (json.JSONDecodeError, ValidationError, AttributeError):
        return []
    known = {o["id"] for o in summary.get("objects", [])}
    result = []
    for request in parsed:
        dumped = request.model_dump(exclude_none=True)
        target = dumped.get("target")
        if isinstance(target, dict) and "id" in target and target["id"] not in known:
            return []  # A hallucinated object id invalidates the whole proposal.
        if dumped["type"] == "scene.remove":
            return []  # Destructive proposals from a model are never accepted.
        result.append(dumped)
    return result
