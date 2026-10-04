"""Bounded, offline GLB validation, inspection and non-destructive normalisation.

The inspector never modifies the source file. It validates the binary container
and every index reference, computes bind-pose bounds through the default
scene's node hierarchy and derives a *normalisation transform* (ground pivot,
optional rescale) that the renderer applies above the untouched asset.

Scope: glTF 2.0 binary containers with one embedded buffer. Extensions that
need decoders the Spatial Lab renderer does not ship (Draco, meshopt, KTX2) are
rejected with a clear reason instead of failing later in the browser.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.history.canonical import quantize

MAX_GLB_BYTES = 48 * 1024 * 1024  # Below the desktop IPC response limit (60 MiB).
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_ELEMENTS = 4_000_000
INSPECTOR_VERSION = "spatial-glb-2"
TARGET_HEIGHT = 1.6
NATIVE_RANGE = (0.2, 3.0)

SUPPORTED_REQUIRED_EXTENSIONS = {
    "KHR_materials_unlit", "KHR_texture_transform", "KHR_mesh_quantization",
    "KHR_materials_emissive_strength", "KHR_materials_ior", "KHR_materials_specular",
    "KHR_materials_transmission", "KHR_materials_volume", "KHR_materials_clearcoat",
    "KHR_materials_sheen", "KHR_materials_iridescence", "KHR_materials_anisotropy",
    "KHR_materials_dispersion", "KHR_lights_punctual",
}
# FORM names Blender objects "<source mesh id[:36]>-<16 hex>"; HUD meshes are
# "hud-ring-<n>" (backend/app/expertise/production/geometry.py).
FORM_HUD_NODE = re.compile(r"^hud-ring-\d+-[0-9a-f]{16}$")
FORM_NODE = re.compile(r"^[a-z0-9_.-]{1,36}-[0-9a-f]{16}$")

COMPONENT_SIZES = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
TYPE_WIDTHS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}


class GlbInvalid(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _fail(code: str, message: str) -> GlbInvalid:
    return GlbInvalid(code, message)


# --------------------------------------------------------------------------------
# Container
# --------------------------------------------------------------------------------
def parse_container(data: bytes) -> Tuple[Dict[str, Any], memoryview]:
    if len(data) > MAX_GLB_BYTES:
        raise _fail("too_large", f"GLB exceeds the {MAX_GLB_BYTES // (1024 * 1024)} MiB Spatial Lab budget.")
    if len(data) < 20:
        raise _fail("not_glb", "File is too small to be a GLB.")
    magic, version, length = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF":
        raise _fail("not_glb", "File is not a binary glTF (missing glTF magic). Text .gltf with external files is not supported.")
    if version != 2:
        raise _fail("unsupported_version", f"glTF container version {version} is not supported; version 2 is required.")
    if length != len(data):
        raise _fail("corrupt", "GLB declared length does not match the file size (truncated or padded file).")
    offset = 12
    chunks: List[Tuple[bytes, int, int]] = []
    while offset < length:
        if offset + 8 > length:
            raise _fail("corrupt", "GLB chunk header is truncated.")
        chunk_length, chunk_type = struct.unpack_from("<I4s", data, offset)
        offset += 8
        if offset + chunk_length > length:
            raise _fail("corrupt", "GLB chunk exceeds the file.")
        chunks.append((chunk_type, offset, chunk_length))
        offset += chunk_length
    if not chunks or chunks[0][0] != b"JSON":
        raise _fail("corrupt", "GLB must start with a JSON chunk.")
    _, json_offset, json_length = chunks[0]
    if not 0 < json_length <= MAX_JSON_BYTES:
        raise _fail("corrupt", "GLB JSON chunk is empty or exceeds its budget.")
    try:
        document = json.loads(bytes(data[json_offset:json_offset + json_length]).decode("utf-8").rstrip(" \x00"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _fail("corrupt", "GLB JSON chunk is not valid UTF-8 JSON.") from exc
    if not isinstance(document, dict):
        raise _fail("corrupt", "GLB JSON root must be an object.")
    binaries = [c for c in chunks[1:] if c[0] == b"BIN\x00"]
    if len(binaries) > 1:
        raise _fail("corrupt", "GLB has more than one binary chunk.")
    view = memoryview(data)
    binary = view[binaries[0][1]:binaries[0][1] + binaries[0][2]] if binaries else view[0:0]
    return document, binary


# --------------------------------------------------------------------------------
# Reference validation
# --------------------------------------------------------------------------------
def _index(document: Dict[str, Any], key: str, number: Any) -> Dict[str, Any]:
    items = document.get(key, [])
    if type(number) is not int or not isinstance(items, list) or not 0 <= number < len(items) or not isinstance(items[number], dict):
        raise _fail("invalid_reference", f"Invalid {key} reference {number!r}.")
    return items[number]


def _accessor_width(accessor: Dict[str, Any]) -> int:
    component = COMPONENT_SIZES.get(accessor.get("componentType"), 0)
    kind = accessor.get("type")
    width = component * TYPE_WIDTHS.get(kind, 0)
    if kind in {"MAT2", "MAT3", "MAT4"} and component:
        columns = int(kind[-1])
        width = columns * (((columns * component + 3) // 4) * 4)
    return width


def validate(document: Dict[str, Any], binary: memoryview) -> None:
    asset = document.get("asset")
    if not isinstance(asset, dict) or asset.get("version") != "2.0":
        raise _fail("unsupported_version", "glTF asset.version must be 2.0.")
    required = document.get("extensionsRequired", [])
    if not isinstance(required, list):
        raise _fail("corrupt", "extensionsRequired must be a list.")
    unsupported = sorted(str(e) for e in required if e not in SUPPORTED_REQUIRED_EXTENSIONS)
    if unsupported:
        raise _fail("unsupported_extension",
                    "GLB requires extensions Spatial Lab V1 cannot decode: " + ", ".join(unsupported[:6]) +
                    ". Re-export without Draco/meshopt/KTX2 compression.")
    buffers = document.get("buffers", [])
    if not isinstance(buffers, list) or len(buffers) > 1:
        raise _fail("external_resource", "GLB must use at most one embedded buffer.")
    for buffer in buffers:
        if not isinstance(buffer, dict) or "uri" in buffer:
            raise _fail("external_resource", "GLB buffers must be embedded; external files and data URIs are refused.")
        if type(buffer.get("byteLength")) is not int or buffer["byteLength"] > len(binary):
            raise _fail("corrupt", "GLB buffer is larger than its binary chunk.")
    for view in document.get("bufferViews", []):
        if not isinstance(view, dict):
            raise _fail("corrupt", "Invalid bufferView.")
        buffer = _index(document, "buffers", view.get("buffer"))
        start, length = view.get("byteOffset", 0), view.get("byteLength")
        if type(start) is not int or type(length) is not int or start < 0 or length < 0 or start + length > buffer["byteLength"]:
            raise _fail("corrupt", "GLB bufferView exceeds its buffer.")
    total = 0
    for accessor in document.get("accessors", []):
        if not isinstance(accessor, dict):
            raise _fail("corrupt", "Invalid accessor.")
        count, offset, width = accessor.get("count"), accessor.get("byteOffset", 0), _accessor_width(accessor)
        if not width or type(count) is not int or not 0 <= count <= MAX_ELEMENTS or type(offset) is not int or offset < 0:
            raise _fail("corrupt", "Invalid accessor layout.")
        total += count
        if total > MAX_ELEMENTS * 4:
            raise _fail("too_complex", "GLB exceeds the Spatial Lab element budget.")
        if "bufferView" in accessor:
            view = _index(document, "bufferViews", accessor["bufferView"])
            stride = view.get("byteStride", width)
            if type(stride) is not int or stride < width or offset + (max(0, count - 1) * stride + width if count else 0) > view["byteLength"]:
                raise _fail("corrupt", "Accessor exceeds its bufferView.")
        elif offset:
            raise _fail("corrupt", "Zero-initialised accessor cannot have a byte offset.")
        if accessor.get("sparse") is not None:
            sparse = accessor["sparse"]
            if not isinstance(sparse, dict) or type(sparse.get("count")) is not int or not 1 <= sparse["count"] <= count:
                raise _fail("corrupt", "Invalid sparse accessor.")
            _index(document, "bufferViews", sparse.get("indices", {}).get("bufferView"))
            _index(document, "bufferViews", sparse.get("values", {}).get("bufferView"))
    for image in document.get("images", []):
        if not isinstance(image, dict) or "uri" in image or "bufferView" not in image:
            raise _fail("external_resource", "GLB images must be embedded; external or data URIs are refused.")
        _index(document, "bufferViews", image["bufferView"])
    for texture in document.get("textures", []):
        if isinstance(texture, dict) and "source" in texture:
            _index(document, "images", texture["source"])
    for mesh in document.get("meshes", []):
        if not isinstance(mesh, dict) or not isinstance(mesh.get("primitives"), list) or not mesh["primitives"]:
            raise _fail("corrupt", "Mesh has no primitives.")
        for primitive in mesh["primitives"]:
            attributes = primitive.get("attributes") if isinstance(primitive, dict) else None
            if not isinstance(attributes, dict) or "POSITION" not in attributes:
                raise _fail("corrupt", "Mesh primitive has no POSITION attribute.")
            for value in attributes.values():
                _index(document, "accessors", value)
            if "indices" in primitive:
                _index(document, "accessors", primitive["indices"])
            if "material" in primitive:
                _index(document, "materials", primitive["material"])
            for target in primitive.get("targets", []):
                for value in target.values():
                    _index(document, "accessors", value)
    nodes = document.get("nodes", [])
    for node in nodes:
        if not isinstance(node, dict):
            raise _fail("corrupt", "Invalid node.")
        for field, key in (("mesh", "meshes"), ("skin", "skins"), ("camera", "cameras")):
            if field in node:
                _index(document, key, node[field])
        for child in node.get("children", []):
            _index(document, "nodes", child)
    parents: Dict[int, int] = {}
    for number, node in enumerate(nodes):
        for child in node.get("children", []):
            if child in parents or child == number:
                raise _fail("corrupt", "Node hierarchy is not a tree (shared or self-referencing child).")
            parents[child] = number
    for start in range(len(nodes)):
        seen, current = set(), start
        while current in parents:
            if current in seen:
                raise _fail("corrupt", "Node hierarchy contains a cycle.")
            seen.add(current)
            current = parents[current]
    for skin in document.get("skins", []):
        joints = skin.get("joints") if isinstance(skin, dict) else None
        if not isinstance(joints, list) or not joints:
            raise _fail("corrupt", "Skin has no joints.")
        for joint in joints:
            _index(document, "nodes", joint)
        if "inverseBindMatrices" in skin:
            _index(document, "accessors", skin["inverseBindMatrices"])
    for animation in document.get("animations", []):
        samplers = animation.get("samplers", []) if isinstance(animation, dict) else None
        if not isinstance(samplers, list):
            raise _fail("corrupt", "Invalid animation.")
        for sampler in samplers:
            _index(document, "accessors", sampler.get("input"))
            _index(document, "accessors", sampler.get("output"))
        for channel in animation.get("channels", []):
            sampler = channel.get("sampler")
            if type(sampler) is not int or not 0 <= sampler < len(samplers):
                raise _fail("corrupt", "Animation channel references a missing sampler.")
            target = channel.get("target", {})
            if "node" in target:
                _index(document, "nodes", target["node"])
    scenes = document.get("scenes", [])
    if not isinstance(scenes, list) or not scenes:
        raise _fail("missing_scene", "GLB has no scene to display.")
    scene_index = document.get("scene", 0)
    scene = _index(document, "scenes", scene_index)
    for root in scene.get("nodes", []):
        _index(document, "nodes", root)
        if root in parents:
            raise _fail("corrupt", "Scene root node is also a child node.")


# --------------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------------
Matrix = List[float]  # column-major 4x4, like glTF


def _identity() -> Matrix:
    return [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]


def _multiply(a: Matrix, b: Matrix) -> Matrix:
    out = [0.0] * 16
    for column in range(4):
        for row in range(4):
            out[column * 4 + row] = sum(a[k * 4 + row] * b[column * 4 + k] for k in range(4))
    return out


def _local_matrix(node: Dict[str, Any]) -> Matrix:
    if "matrix" in node:
        matrix = node["matrix"]
        if not isinstance(matrix, list) or len(matrix) != 16 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in matrix):
            raise _fail("corrupt", "Node matrix is invalid.")
        return [float(v) for v in matrix]
    t = node.get("translation", [0, 0, 0])
    r = node.get("rotation", [0, 0, 0, 1])
    s = node.get("scale", [1, 1, 1])
    for value, size in ((t, 3), (r, 4), (s, 3)):
        if not isinstance(value, list) or len(value) != size or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in value):
            raise _fail("corrupt", "Node TRS is invalid.")
    x, y, z, w = r
    xx, yy, zz, xy, xz, yz, wx, wy, wz = x * x, y * y, z * z, x * y, x * z, y * z, w * x, w * y, w * z
    rotation = [
        1 - 2 * (yy + zz), 2 * (xy + wz), 2 * (xz - wy),
        2 * (xy - wz), 1 - 2 * (xx + zz), 2 * (yz + wx),
        2 * (xz + wy), 2 * (yz - wx), 1 - 2 * (xx + yy),
    ]
    return [
        rotation[0] * s[0], rotation[1] * s[0], rotation[2] * s[0], 0.0,
        rotation[3] * s[1], rotation[4] * s[1], rotation[5] * s[1], 0.0,
        rotation[6] * s[2], rotation[7] * s[2], rotation[8] * s[2], 0.0,
        float(t[0]), float(t[1]), float(t[2]), 1.0,
    ]


def _transform_point(m: Matrix, p: Sequence[float]) -> List[float]:
    x, y, z = p
    return [m[0] * x + m[4] * y + m[8] * z + m[12], m[1] * x + m[5] * y + m[9] * z + m[13], m[2] * x + m[6] * y + m[10] * z + m[14]]


def _position_bounds(document: Dict[str, Any], binary: memoryview, accessor_index: int) -> Optional[Tuple[List[float], List[float]]]:
    accessor = document["accessors"][accessor_index]
    if accessor.get("type") != "VEC3":
        raise _fail("corrupt", "POSITION accessor must be VEC3.")
    low, high = accessor.get("min"), accessor.get("max")
    if isinstance(low, list) and isinstance(high, list) and len(low) == 3 and len(high) == 3:
        if all(isinstance(v, (int, float)) and math.isfinite(v) for v in low + high):
            return [float(v) for v in low], [float(v) for v in high]
        raise _fail("corrupt", "POSITION bounds are not finite.")
    # Spec requires min/max for POSITION; compute only for well-formed float data.
    if accessor.get("componentType") != 5126 or "bufferView" not in accessor or accessor.get("sparse"):
        return None
    view = document["bufferViews"][accessor["bufferView"]]
    stride = view.get("byteStride", 12)
    base = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    count = accessor["count"]
    if count == 0:
        return None
    low, high = [math.inf] * 3, [-math.inf] * 3
    for i in range(count):
        point = struct.unpack_from("<3f", binary, base + i * stride)
        if not all(math.isfinite(v) for v in point):
            raise _fail("corrupt", "POSITION data contains non-finite values.")
        for axis in range(3):
            low[axis] = min(low[axis], point[axis])
            high[axis] = max(high[axis], point[axis])
    return low, high


def _animation_duration(document: Dict[str, Any], binary: memoryview, animation: Dict[str, Any]) -> float:
    duration = 0.0
    for sampler in animation.get("samplers", []):
        accessor = document["accessors"][sampler["input"]]
        high = accessor.get("max")
        if isinstance(high, list) and high and isinstance(high[0], (int, float)) and math.isfinite(high[0]):
            duration = max(duration, float(high[0]))
        elif accessor.get("componentType") == 5126 and "bufferView" in accessor and accessor["count"]:
            view = document["bufferViews"][accessor["bufferView"]]
            base = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
            stride = view.get("byteStride", 4)
            last = struct.unpack_from("<f", binary, base + (accessor["count"] - 1) * stride)[0]
            if math.isfinite(last):
                duration = max(duration, last)
    return round(duration, 4)


def _clean_name(value: Any, fallback: str, limit: int = 80) -> str:
    text = value if isinstance(value, str) else ""
    text = "".join(ch for ch in text if ch.isprintable()).strip()[:limit]
    return text or fallback


def inspect(data: bytes) -> Dict[str, Any]:
    document, binary = parse_container(data)
    validate(document, binary)
    nodes = document.get("nodes", [])
    scene = document["scenes"][document.get("scene", 0)]
    worlds: Dict[int, Matrix] = {}
    stack = [(root, _identity()) for root in scene.get("nodes", [])]
    while stack:
        number, parent = stack.pop()
        world = _multiply(parent, _local_matrix(nodes[number]))
        worlds[number] = world
        stack.extend((child, world) for child in nodes[number].get("children", []))
    low, high = [math.inf] * 3, [-math.inf] * 3
    vertices = triangles = primitives = morphs = 0
    skinned = False
    for number, world in worlds.items():
        node = nodes[number]
        if "mesh" not in node:
            continue
        skinned = skinned or "skin" in node
        for primitive in document["meshes"][node["mesh"]]["primitives"]:
            primitives += 1
            morphs += len(primitive.get("targets", []))
            position = primitive["attributes"]["POSITION"]
            vertices += document["accessors"][position]["count"]
            mode = primitive.get("mode", 4)
            if mode == 4:
                count = document["accessors"][primitive["indices"]]["count"] if "indices" in primitive else document["accessors"][position]["count"]
                triangles += count // 3
            bounds = _position_bounds(document, binary, position)
            if not bounds:
                continue
            (x0, y0, z0), (x1, y1, z1) = bounds
            for corner in ((x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)):
                point = _transform_point(world, corner)
                for axis in range(3):
                    low[axis] = min(low[axis], point[axis])
                    high[axis] = max(high[axis], point[axis])
    if not all(math.isfinite(v) for v in low + high):
        raise _fail("no_geometry", "The default scene contains no measurable mesh geometry.")
    size = [high[i] - low[i] for i in range(3)]
    largest = max(size)
    if not 1e-5 <= largest <= 1e6:
        raise _fail("degenerate_bounds", f"Asset bounds are degenerate (largest extent {largest:.3g}).")
    names = [_clean_name(n.get("name"), f"node {i}") for i, n in enumerate(nodes)]
    joint_nodes = sorted({j for skin in document.get("skins", []) for j in skin["joints"]})
    clips, used = [], set()
    for index, animation in enumerate(document.get("animations", [])):
        name = _clean_name(animation.get("name"), f"Animation {index + 1}")
        base, suffix = name, 2
        while name in used:
            name, suffix = f"{base} ({suffix})", suffix + 1
        used.add(name)
        paths = sorted({c.get("target", {}).get("path", "?") for c in animation.get("channels", [])})
        targets = {c.get("target", {}).get("node") for c in animation.get("channels", [])}
        clips.append({
            "index": index,
            "name": name,
            "duration": _animation_duration(document, binary, animation),
            "channels": len(animation.get("channels", [])),
            "paths": [str(p) for p in paths][:8],
            "targets_joints": bool(targets & set(joint_nodes)),
        })
    hud_nodes = [names[i] for i in range(len(nodes)) if FORM_HUD_NODE.match(names[i])]
    hud_indices = {i for i in range(len(nodes)) if FORM_HUD_NODE.match(names[i])}
    for clip, animation in zip(clips, document.get("animations", [])):
        targets = {c.get("target", {}).get("node") for c in animation.get("channels", [])} - {None}
        paths = set(clip["paths"])
        if clip["targets_joints"]:
            kind = "skeletal"
        elif paths == {"weights"} and targets and targets <= hud_indices:
            kind = "hud_morph"  # FORM HUD energy flow (shape keys on hud-ring meshes)
        elif paths == {"weights"}:
            kind = "morph"
        else:
            kind = "node"
        clip["kind"] = kind
        clip["targets"] = sorted(names[t] for t in targets if isinstance(t, int))[:8]
    warnings: List[str] = []
    unbound = [names[i] for i in worlds if "mesh" in nodes[i] and "skin" not in nodes[i]
               and any("JOINTS_0" in p["attributes"] for p in document["meshes"][nodes[i]["mesh"]]["primitives"])]
    if unbound:
        warnings.append(f"{len(unbound)} node(s) use skinned geometry without a skin (e.g. '{unbound[0]}'); rendered as static geometry.")
    normalization = normalize(low, high, skinned)
    generator = _clean_name(document["asset"].get("generator"), "unknown", 120)
    return {
        "inspector": INSPECTOR_VERSION,
        "format": "glb",
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "generator": generator,
        "nodes": len(nodes),
        "meshes": len(document.get("meshes", [])),
        "primitives": primitives,
        "vertices": vertices,
        "triangles": triangles,
        "materials": len(document.get("materials", [])),
        "images": len(document.get("images", [])),
        "skins": len(document.get("skins", [])),
        "joints": len(joint_nodes),
        "joint_names": [names[j] for j in joint_nodes][:96],
        "morph_targets": morphs,
        "clips": clips,
        "form_hud_nodes": hud_nodes[:32],
        "form_naming": sum(1 for n in names if FORM_NODE.match(n)),
        "extensions_used": sorted(str(e) for e in document.get("extensionsUsed", []))[:20],
        "bounds": {"min": [quantize(v) for v in low], "max": [quantize(v) for v in high]},
        "bounds_method": "bind_pose_node_transform" + ("_approximation_for_skinned_meshes" if skinned else ""),
        "normalization": normalization,
        "warnings": warnings,
    }


def normalize(low: Sequence[float], high: Sequence[float], skinned: bool) -> Dict[str, Any]:
    size = [high[i] - low[i] for i in range(3)]
    largest = max(size)
    center = [(high[i] + low[i]) / 2 for i in range(3)]
    flags: List[str] = []
    fit = size[1] if size[1] >= 0.25 * largest else largest
    scale = 1.0
    if fit < NATIVE_RANGE[0]:
        scale = TARGET_HEIGHT / fit
        flags.append("rescaled_tiny")
    elif fit > NATIVE_RANGE[1]:
        scale = TARGET_HEIGHT / fit
        flags.append("rescaled_enormous" if fit < 100 else "rescaled_unit_mismatch")
    if abs(center[0]) > 0.1 * largest or abs(center[2]) > 0.1 * largest or abs(low[1]) > 0.1 * largest:
        flags.append("pivot_recentered")
    if size[2] > 2.5 * max(size[1], 1e-9) and size[2] >= size[0]:
        flags.append("orientation_suspect_z_up")
    return {
        "scale": quantize(scale, 9),
        "offset": [quantize(-center[0]), quantize(-low[1]), quantize(-center[2])],
        "native_size": [quantize(v) for v in size],
        "size": [quantize(v * scale) for v in size],
        "pivot": "ground_center",
        "up_axis": "+Y (glTF)",
        "flags": flags,
        "scope": "Display normalisation only; the source file is never modified.",
    }
