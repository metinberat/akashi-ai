"""Deterministic Turkish/English replies describing what actually happened.

Replies are built from the applied request and the resulting scene, never from
model prose, so AKASHI only reports changes the reducer really made.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.spatial.geometry import yaw_degrees


def _label(state: Dict[str, Any], result: Any) -> str:
    targets = getattr(result, "targets", None) if not isinstance(result, dict) else result.get("targets")
    for key in targets or []:
        if key in state["objects"]:
            return state["objects"][key]["label"]
    events = result.get("events", []) if isinstance(result, dict) else []
    return events[0]["summary"].split(" ", 1)[-1] if events else "the object"


def describe(request: Any, result: Any, state: Dict[str, Any], language: str, pending: bool = False) -> str:
    tr = language == "tr"
    label = _label(state, result)
    kind = request.type
    if pending:
        if kind == "scene.remove":
            return f"{label} sahneden kaldırılsın mı?" if tr else f"Remove {label} from the scene?"
        return "Onaylıyor musun?" if tr else "Confirm this change?"
    status = result.get("status") if isinstance(result, dict) else None
    if status == "noop":
        return "Zaten öyle; değişiklik yapılmadı." if tr else "Already like that; nothing changed."
    notes = " ".join(result.get("notes", [])) if isinstance(result, dict) else ""
    obj = next((state["objects"][k] for k in (result.get("targets") or []) if k in state["objects"]), None) if isinstance(result, dict) else None
    text = ""
    if kind == "history.undo":
        summary = result["events"][0]["summary"] if result.get("events") else ""
        text = f"Geri alındı: {summary.removeprefix('Undo: ')}." if tr else f"Undone: {summary.removeprefix('Undo: ')}."
    elif kind == "history.redo":
        summary = result["events"][0]["summary"] if result.get("events") else ""
        text = f"Yinelendi: {summary.removeprefix('Redo: ')}." if tr else f"Redone: {summary.removeprefix('Redo: ')}."
    elif kind == "scene.add_asset":
        form = (obj or {}).get("asset", {}).get("form") or {}
        verified = " (FORM kimliği doğrulandı)" if tr and form.get("identity_verified") else " (FORM identity verified)" if form.get("identity_verified") else ""
        text = f"{label} yüklendi{verified}." if tr else f"Loaded {label}{verified}."
    elif kind == "scene.remove":
        text = "Nesne sahneden kaldırıldı." if tr else "Removed the object from the scene."
    elif kind == "selection.select":
        text = (f"{label} seçildi." if tr else f"Selected {label}.") if request.target else ("Seçim temizlendi." if tr else "Selection cleared.")
    elif kind == "view.inspect":
        text = f"{label} inceleniyor." if tr else f"Inspecting {label}."
    elif kind == "object.transform" and obj:
        t = obj["transform"]
        mode = request.mode
        if mode == "scale":
            text = f"{label} artık {t['scale']:.2f}× boyutta." if tr else f"{label} is now {t['scale']:.2f}× size."
        elif mode == "rotate":
            text = f"{label} {request.degrees:g}° döndürüldü." if tr else f"Rotated {label} {request.degrees:g}° (heading {yaw_degrees(t['rotation']):g}°)."
        elif mode == "to_anchor":
            hand = ("sağ" if tr else "right") if request.anchor == "right_hand" else ("sol" if tr else "left")
            text = f"{label} {hand} eline taşındı." if tr else f"Moved {label} to your {hand} hand."
        elif mode == "center":
            text = f"{label} merkeze alındı." if tr else f"{label} is back in the center."
        elif mode == "reset":
            text = f"{label} varsayılan konuma döndü." if tr else f"Reset {label}'s position, rotation and size."
        elif mode == "translate":
            text = f"{label} taşındı." if tr else f"Moved {label}."
        else:
            text = f"{label} konumlandırıldı." if tr else f"Placed {label}."
    elif kind == "object.display" and obj:
        parts = []
        for key, en, trn in (("skeleton", "rig", "iskelet"), ("form_hud", "FORM HUD", "FORM HUD"), ("bounds", "bounds", "sınır kutusu")):
            value = getattr(request, key)
            if value is not None:
                parts.append((trn + (" açık" if value else " gizli")) if tr else (en + (" shown" if value else " hidden")))
        text = f"{label}: " + ", ".join(parts) + "."
    elif kind == "object.visibility":
        text = (f"{label} gösteriliyor." if request.visible else f"{label} gizlendi.") if tr else (f"{label} is visible." if request.visible else f"{label} is hidden.")
    elif kind == "animation.control" and obj:
        clip = obj["animation"]["clip"]
        if obj["animation"]["playing"]:
            text = f"{label} üzerinde {clip} oynatılıyor." if tr else f"Playing {clip} on {label}."
        else:
            text = f"{label} animasyonu durduruldu." if tr else f"Animation paused on {label}." if clip else f"Animation stopped on {label}."
    elif kind == "object.version" and obj:
        form = obj["asset"].get("form") or {}
        text = f"{form.get('project_name', label)} artık {form.get('version_label')} gösteriyor (kimlik doğrulandı)." if tr else \
            f"{form.get('project_name', label)} now shows {form.get('version_label')} (FORM identity verified)."
    elif kind == "object.rename":
        text = f"Yeni ad: {label}." if tr else f"Renamed to {label}."
    elif kind == "view.set":
        parts = []
        if request.hud_visible is not None:
            parts.append(("HUD " + ("açık" if request.hud_visible else "gizli")) if tr else ("HUD " + ("shown" if request.hud_visible else "hidden")))
        if request.vfx_visible is not None:
            parts.append(("VFX " + ("açık" if request.vfx_visible else "kapalı")) if tr else ("VFX " + ("on" if request.vfx_visible else "off")))
        text = ", ".join(parts) + "."
    else:
        text = "Tamam." if tr else "Done."
    return (text + (" " + notes if notes else "")).strip()


FAILURES = {
    "not_understood": ("Bunu bir sahne komutu olarak anlayamadım. Örnek: “büyüt”, “180 derece döndür”, “iskeleti göster”.",
                       "I couldn't read that as a scene command. Try “make it bigger”, “rotate it 180 degrees” or “show the rig”."),
    "confirmation_required": ("Onay gerekiyor: {detail}", "Confirmation needed: {detail}"),
}


TURKISH_DETAILS = {
    "deictic_ambiguous": "Hangi nesneyi kastediyorsun?",
    "deictic_none": "Sahne boş.",
    "only_ambiguous": "Sahnede birden fazla nesne var. Hangisi?",
    "selected_none": "Seçili bir nesne yok.",
    "anchor_unavailable": "O elini şu an göremiyorum. Elini kameraya gösterip tekrar dene.",
    "form_none": "Sahnede FORM karakteri yok.",
    "form_ambiguous": "Sahnede birden fazla FORM karakteri var. Hangisi?",
    "object_busy": "Bu nesne şu an elinde tutuluyor. Önce bırak.",
    "last_moved_none": "Henüz hiçbir şey taşınmadı.",
    "leftmost_tie": "Solda aynı hizada birden fazla nesne var. Hangisi?",
    "rightmost_tie": "Sağda aynı hizada birden fazla nesne var. Hangisi?",
    "largest_tie": "Aynı büyüklükte birden fazla nesne var. Hangisi?",
    "nothing_to_undo": "Geri alınacak bir şey yok.",
    "nothing_to_redo": "Yinelenecek bir şey yok.",
}


def failure_reply(code: str, language: str, detail: Optional[str] = None) -> str:
    tr = language == "tr"
    if tr and code in TURKISH_DETAILS:
        return TURKISH_DETAILS[code]
    if code in FAILURES:
        template = FAILURES[code][0 if tr else 1]
        return template.format(detail=detail or "")
    return detail or ("İstek uygulanamadı." if tr else "The request could not be applied.")
