"""Bounded local reference measurements and explicit image-space comparison.

No semantic vision claims: palette/silhouette cannot certify character fidelity.
Uniform-background or alpha references support masks; complex backgrounds abstain.
"""

import hashlib
import io
import math
from collections import Counter
from PIL import Image, ImageOps

VISUAL_VERSION = "local-reference-1"


def _pixels(image):
    # Support the current Pillow API without breaking existing Pillow 11 runtimes.
    return (
        image.get_flattened_data()
        if hasattr(image, "get_flattened_data")
        else image.getdata()
    )


def _measure(raw):
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError("Reference exceeds the analysis budget.")
    with Image.open(io.BytesIO(raw)) as source:
        if source.width * source.height > 16000000:
            raise ValueError("Reference pixel budget exceeded.")
        image = ImageOps.exif_transpose(source).convert("RGBA")
        size = image.size
        image.thumbnail((256, 256))
    w, h = image.size
    pixels = list(_pixels(image))
    border = [pixels[x] for x in range(w)] + [pixels[(h - 1) * w + x] for x in range(w)]
    border += [pixels[y * w] for y in range(h)] + [
        pixels[y * w + w - 1] for y in range(h)
    ]
    background = tuple(sorted(p[c] for p in border)[len(border) // 2] for c in range(3))
    uniform = sum(
        max(abs(p[c] - background[c]) for c in range(3)) < 26 for p in border
    ) / len(border)
    alpha = any(p[3] < 32 for p in pixels)
    supported = alpha or uniform >= 0.92
    mask = Image.new("L", (w, h))
    bits = [
        255
        if (
            p[3] > 96
            if alpha
            else max(abs(p[c] - background[c]) for c in range(3)) > 32
        )
        else 0
        for p in pixels
    ]
    mask.putdata(bits)
    box = mask.getbbox() if supported else None
    coverage = sum(v > 0 for v in bits) / len(bits)
    supported = bool(
        box and 0.015 < coverage < 0.90 and box[2] - box[0] > 3 and box[3] - box[1] > 3
    )
    if not supported:
        box = None
    colors = Counter(
        tuple((p[c] // 24) * 24 + 12 for c in range(3))
        for i, p in enumerate(pixels)
        if p[3] > 96 and (not supported or bits[i])
    )
    total = max(1, sum(colors.values()))
    palette = [
        {"rgb": [min(255, c) / 255 for c in color], "fraction": count / total}
        for color, count in colors.most_common(8)
    ]
    evidence = {
        "version": VISUAL_VERSION,
        "image_sha256": hashlib.sha256(raw).hexdigest(),
        "dimensions": list(size),
        "palette": palette,
        "palette_scope": "foreground" if supported else "whole_image_not_character",
        "mask_status": "measured" if supported else "ambiguous_background_or_empty",
        "background_uniformity": uniform,
        "foreground_fraction": coverage if supported else None,
        "foreground_box": [box[0] / w, box[1] / h, box[2] / w, box[3] / h]
        if box
        else None,
        "silhouette_aspect": (box[2] - box[0]) / (box[3] - box[1]) if box else None,
        "observed": ["decoded pixels", "quantized colors"],
        "unknown": [
            "semantic identity",
            "hidden anatomy",
            "topology",
            "pose alignment",
            "production quality",
        ],
    }
    return evidence, mask.crop(box) if box else None


def analyze(raw):
    return _measure(raw)[0]


def compare(reference, render):
    a, ma = _measure(reference)
    b, mb = _measure(render)
    result = {
        "version": VISUAL_VERSION,
        "reference_sha256": a["image_sha256"],
        "render_sha256": b["image_sha256"],
        "scope": "image-space silhouette/palette proxies; NOT semantic or professional fidelity",
        "view_alignment": "user must check pose/view correspondence",
        "professional_quality": "unmeasured",
    }
    if ma is None or mb is None:
        return {
            **result,
            "status": "not_comparable",
            "loss": None,
            "reason": "A reliable foreground mask could not be measured. No fabricated similarity score.",
        }
    ma = ImageOps.pad(ma, (192, 256), Image.Resampling.NEAREST, color=0)
    mb = ImageOps.pad(mb, (192, 256), Image.Resampling.NEAREST, color=0)
    pairs = list(zip(_pixels(ma), _pixels(mb)))
    union = sum(bool(x or y) for x, y in pairs)
    iou = sum(bool(x and y) for x, y in pairs) / max(1, union)

    # Weighted nearest palette colors, in both directions. Shadows remain a limitation.
    def palette_distance(x, y):
        return sum(
            p["fraction"] * min(math.dist(p["rgb"], q["rgb"]) / math.sqrt(3) for q in y)
            for p in x
        )

    color = (
        palette_distance(a["palette"], b["palette"])
        + palette_distance(b["palette"], a["palette"])
    ) / 2
    return {
        **result,
        "status": "measured_proxy",
        "silhouette_iou": iou,
        "palette_distance": color,
        "loss": 0.70 * (1 - iou) + 0.30 * color,
        "decision_scope": "only compare same reference, view and evaluator version",
    }


def advise(brief, observations=None):
    # Explicit heuristic complexity indicators, never a claim of artistic mastery.
    text = brief.casefold()
    demands = {
        "face_detail": ("face", "facial", "yüz", "portrait", "portre"),
        "grooming": ("hair", "fur", "groom", "saç", "kürk"),
        "layered_surface": ("clothing", "fabric", "layer", "kıyafet", "katman", "coat"),
        "cinematic": (
            "cinematic",
            "photoreal",
            "professional",
            "sinematik",
            "gerçekçi",
            "profesyonel",
        ),
        "spatial_effects": ("hud", "hologram", "vfx", "aura", "energy", "enerji"),
        "reference_matching": (
            "exact",
            "identical",
            "reference",
            "birebir",
            "referans",
        ),
    }
    signals = [
        key for key, tokens in demands.items() if any(token in text for token in tokens)
    ]
    difficult = "cinematic" in signals or "reference_matching" in signals
    tier = (
        "professional_quality_unproven"
        if difficult
        else "difficult_locally"
        if len(signals) >= 3
        else "supported_stylized_local"
    )
    return {
        "basis": "declared task cues and current engine limits; heuristic, not measured artistic difficulty",
        "tier": tier,
        "signals": signals,
        "local_can_continue": True,
        "optional_specialist_recommended": difficult,
        "reference_mask": (observations or {}).get("mask_status", "no_reference"),
        "local_capabilities": [
            "parametric face/hair/tailoring",
            "57-joint rig",
            "pose tests",
            "local spatial HUD",
            "Blender render/export",
        ],
        "limits": [
            "segmented anatomy",
            "procedural production does not reconstruct reference anatomy; optional learned shape is separate and unrigged",
            "no professional likeness certification",
        ],
    }


def propose(design, observations):
    """Conservative palette adaptation only for separable references; preserve explicit proportions."""
    result = dict(design)
    result["appearance"] = "atelier"
    if observations and observations.get("palette_scope") == "foreground":
        palette = observations["palette"]
        dark = [p for p in palette if max(p["rgb"]) < 0.45]
        if dark:
            result["cloth_color"] = max(dark, key=lambda p: p["fraction"])["rgb"]
        vivid = [p for p in palette if max(p["rgb"]) - min(p["rgb"]) > 0.25]
        if vivid:
            result["accent_color"] = max(vivid, key=lambda p: p["fraction"])["rgb"]
    return result
