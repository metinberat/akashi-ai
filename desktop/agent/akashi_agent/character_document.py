"""Dependency-free narrow canonical validator for fixed synthetic Blender construction."""
import base64
import hashlib
import json
import math

MAX_BYTES = 32*1024*1024
ROOT_KEYS = {"schema_version", "name", "coordinate_system", "joints", "meshes", "skins", "materials", "animations", "objects", "unavailable", "metadata"}


def validate_document(value, construction=False):
    if not isinstance(value, dict) or value.get("schema_version") != 1 or set(value)-ROOT_KEYS:
        raise ValueError("Unsupported canonical character root.")
    if not isinstance(value.get("name"), str) or not 1 <= len(value["name"]) <= 300:
        raise ValueError("Invalid character name.")
    def finite(item, depth=0):
        if depth > 40:
            raise ValueError("Character nesting exceeds budget.")
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("Non-finite character numeric data.")
        if isinstance(item, dict):
            for child in item.values(): finite(child, depth+1)
        elif isinstance(item, list):
            for child in item: finite(child, depth+1)
    finite(value)
    for field in ("joints", "meshes", "skins", "materials", "animations", "objects"):
        if not isinstance(value.get(field, []), list) or len(value.get(field, [])) > 10000:
            raise ValueError("Invalid character collection.")
    if not construction:
        return value
    if value.get("metadata", {}).get("synthetic") is not True or value["metadata"].get("deformation_space") != "shared_bind":
        raise ValueError("Fixed construction currently accepts synthetic shared-bind geometry only.")
    if value.get("animations") or value.get("objects"):
        raise ValueError("Construction does not reconstruct arbitrary application objects or animation.")
    joints = value.get("joints", [])
    if not 1 <= len(joints) <= 128:
        raise ValueError("Construction skeleton budget exceeded.")
    identifiers = [j.get("id") for j in joints]
    if any(not isinstance(k, str) or not 1 <= len(k) <= 200 for k in identifiers) or len(set(identifiers)) != len(identifiers):
        raise ValueError("Invalid construction joint identifiers.")
    parents = {j["id"]: j.get("parent") for j in joints}
    for joint in joints:
        if joint.get("constraints") or any(joint.get(k) for k in ("matrix", "translation", "rotation", "scale", "inverse_bind_matrix")):
            raise ValueError("Construction cannot silently discard constraints/transforms.")
        metadata = joint.get("metadata", {})
        for key in ("head", "tail"):
            vector = metadata.get(key)
            if not isinstance(vector, list) or len(vector) != 3 or any(type(v) not in (float, int) or abs(v) > 1e6 for v in vector):
                raise ValueError("Construction needs bounded explicit bone segments.")
        if math.dist(metadata["head"], metadata["tail"]) < 1e-8:
            raise ValueError("Degenerate bone segment.")
        seen, cursor = set(), joint["id"]
        while cursor is not None:
            if cursor in seen or cursor not in parents:
                raise ValueError("Invalid hierarchy.")
            seen.add(cursor)
            cursor = parents[cursor]
    meshes, total = {}, 0
    for mesh in value.get("meshes", []):
        key, points, faces = mesh.get("id"), mesh.get("positions"), mesh.get("faces")
        if not isinstance(key, str) or not 1 <= len(key) <= 200 or key in meshes or not isinstance(points, list) or not isinstance(faces, list):
            raise ValueError("Construction requires unique complete meshes.")
        if mesh.get("modifiers") or mesh.get("morph_targets"):
            raise ValueError("Unsupported construction surface features cannot be silently discarded.")
        total += len(points)
        if total > 200000 or len(faces) > 200000 or len(points) != mesh.get("vertex_count"):
            raise ValueError("Construction geometry exceeds budget.")
        if any(not isinstance(p, list) or len(p) != 3 or any(type(v) not in (int, float) or abs(v) > 1e6 for v in p) for p in points):
            raise ValueError("Invalid point.")
        if any(not isinstance(f, list) or not 3 <= len(f) <= 64 or any(type(i) is not int or not 0 <= i < len(points) for i in f) for f in faces):
            raise ValueError("Invalid polygon.")
        meshes[key] = mesh
    bound = set()
    for skin in value.get("skins", []):
        mesh = meshes.get(skin.get("mesh_id"))
        weights = skin.get("weights")
        if not mesh or mesh.get("skin_id") != skin.get("id") or skin["mesh_id"] in bound or not isinstance(weights, list) or len(weights) != mesh["vertex_count"]:
            raise ValueError("Invalid mesh binding.")
        bound.add(skin["mesh_id"])
        if not set(skin.get("joints", [])) <= set(identifiers):
            raise ValueError("Unknown skin joint.")
        for weights_at_vertex in weights:
            if not isinstance(weights_at_vertex, dict) or set(weights_at_vertex)-set(skin["joints"]) or any(type(w) not in (int,float) or w < 0 or w > 1 for w in weights_at_vertex.values()) or abs(sum(weights_at_vertex.values())-1) > 1e-5:
                raise ValueError("Invalid normalized weights.")
    if bound != set(meshes):
        raise ValueError("Every constructed practice surface must be explicitly bound.")
    return value


def read_chunk(paths, arguments):
    source = paths.resolve(str(arguments.get("project") or ""))
    if not source.is_file() or source.suffix.casefold() != ".json" or source.stat().st_size > MAX_BYTES:
        raise ValueError("Canonical readback needs bounded approved JSON.")
    offset, length = arguments.get("offset", 0), arguments.get("length", 48000)
    if type(offset) is not int or offset < 0 or type(length) is not int or not 1 <= length <= 48000:
        raise ValueError("Invalid character readback bounds.")
    content = source.read_bytes()
    validate_document(json.loads(content))
    if offset > len(content):
        raise ValueError("Readback offset exceeds the source.")
    return {"verified": True, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(), "offset": offset,
            "data_base64": base64.b64encode(content[offset:offset+length]).decode(), "complete": offset+length >= len(content)}
