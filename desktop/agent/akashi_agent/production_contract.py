"""Dependency-free production metadata validation at the process boundary."""

try:
    from .character_document import validate_document
except ImportError:  # Fixed Blender script context, not the Agent package.
    from character_document import validate_document


def validate_production(value):
    validate_document(value, construction=True)
    metadata = value.get("metadata", {})
    if metadata.get("production_version") != "character-production-1.0":
        raise ValueError("Unsupported production version.")
    design = metadata.get("production_design", {})
    fields = {
        "height",
        "head_ratio",
        "shoulder_ratio",
        "build",
        "clothing",
        "hair",
        "skin_color",
        "cloth_color",
        "accent_color",
        "hud",
        "facial",
    }
    if set(design) not in (fields, fields | {"appearance"}):
        raise ValueError("Unsupported production design fields.")
    if design.get("appearance", "classic") not in {"classic", "atelier"}:
        raise ValueError("Unsupported appearance profile.")
    for key, lo, hi in (
        ("height", 0.6, 3),
        ("head_ratio", 0.1, 0.22),
        ("shoulder_ratio", 0.18, 0.38),
    ):
        if type(design[key]) not in (int, float) or not lo <= design[key] <= hi:
            raise ValueError("Invalid production proportion.")
    for key in ("skin_color", "cloth_color", "accent_color"):
        if (
            not isinstance(design[key], list)
            or len(design[key]) != 3
            or any(type(v) not in (int, float) or not 0 <= v <= 1 for v in design[key])
        ):
            raise ValueError("Invalid production color.")
    for key, choices in (
        ("build", {"slender", "balanced", "strong"}),
        ("clothing", {"bodysuit", "coat", "armor"}),
        ("hair", {"none", "short", "long"}),
    ):
        if design[key] not in choices:
            raise ValueError("Unsupported authoring feature.")
    if any(type(design[k]) is not bool for k in ("hud", "facial")):
        raise ValueError("Invalid production feature toggle.")
    return value
