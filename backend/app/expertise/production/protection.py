"""Compare protected application structures by identity, not incidental datablock order."""


def protected_equivalence(original, observed):
    for field in ("meshes", "joints", "skins", "animations"):
        before = {v["id"]: v for v in original.get(field, [])}
        after = {v["id"]: v for v in observed.get(field, [])}
        if before != after:
            raise ValueError("Presentation changed protected " + field + ".")
    used = {
        identifier
        for mesh in original.get("meshes", [])
        for identifier in mesh.get("materials", [])
    }
    before = {m["id"]: m for m in original.get("materials", [])}
    after = {m["id"]: m for m in observed.get("materials", [])}
    if any(
        key not in before or key not in after or before[key] != after[key]
        for key in used
    ):
        raise ValueError("Presentation changed an assigned material.")
    return {
        "verified": True,
        "compared": ["meshes", "joints", "skins", "animations", "assigned_materials"],
        "assigned_materials": len(used),
        "orphan_material_scope": "Unassigned Blender datablocks may be purged when saving the new copy; original source bytes remain untouched.",
    }
