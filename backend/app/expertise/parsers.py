"""Bounded, offline parsers. External glTF URIs are never fetched or opened."""
from __future__ import annotations

import base64
import json
import math
import struct
from pathlib import Path
from typing import Any, Dict, List, Tuple

from app.expertise.schema import CharacterDocument
from app.expertise.sparse import apply_sparse

PARSER_VERSION = "interchange-1.1"
MAX_BYTES = 32 * 1024 * 1024
MAX_SAMPLES = 200000


def _reference(items: List[Any], index: Any, label: str) -> Any:
    if not isinstance(index, int) or isinstance(index, bool) or index < 0 or index >= len(items):
        raise ValueError("Invalid " + label + " reference.")
    return items[index]


def _json(content: bytes) -> Dict[str, Any]:
    value = json.loads(content.decode("utf-8-sig"), parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("Non-finite JSON number.")))
    if not isinstance(value, dict):
        raise ValueError("Asset root must be an object.")
    return value


def parse_asset(filename: str, content: bytes) -> Tuple[CharacterDocument, Dict[str, Any]]:
    if not content or len(content) > MAX_BYTES:
        raise ValueError("Character source must contain 1 byte to 32 MiB.")
    suffix = Path(filename).suffix.lower()
    if suffix == ".json":
        raw = _json(content)
        document = CharacterDocument.model_validate(raw)
    elif suffix in {".gltf", ".glb"}:
        raw, binary = read_gltf(content, suffix)
        document = parse_gltf(raw, binary, Path(filename).stem)
    elif suffix == ".obj":
        document, raw = parse_obj(content.decode("utf-8-sig"), Path(filename).stem)
    else:
        raise ValueError("Supported sources: canonical .json, embedded .gltf/.glb, .obj. Export FBX/.blend through the fixed Blender inspection adapter; direct parsing is unavailable.")
    # Reject non-finite nested metadata/weights as well as transforms.
    json.dumps(document.model_dump(), allow_nan=False)
    return document, raw


def read_gltf(content: bytes, suffix: str) -> Tuple[Dict[str, Any], List[bytes]]:
    binary: List[bytes] = []
    if suffix == ".gltf":
        return _json(content), binary
    if len(content) < 20:
        raise ValueError("Truncated GLB.")
    magic, version, length = struct.unpack_from("<4sII", content)
    if magic != b"glTF" or version != 2 or length != len(content):
        raise ValueError("Invalid GLB header/version/length.")
    offset, document = 12, None
    while offset < length:
        if offset + 8 > length:
            raise ValueError("Truncated GLB chunk header.")
        size, kind = struct.unpack_from("<II", content, offset)
        offset += 8
        if offset + size > length:
            raise ValueError("Truncated GLB chunk.")
        chunk = content[offset:offset + size]
        offset += size
        if kind == 0x4E4F534A:
            if document is not None:
                raise ValueError("Multiple GLB JSON chunks.")
            document = _json(chunk.rstrip(b" \x00"))
        elif kind == 0x004E4942:
            binary.append(chunk)
    if document is None:
        raise ValueError("Missing GLB JSON chunk.")
    return document, binary


class Accessors:
    def __init__(self, data: Dict[str, Any], binary: List[bytes]) -> None:
        self.data = data
        self.buffers: List[bytes] = []
        self.unavailable: List[str] = []
        self._cache: Dict[int, List[Any]] = {}
        self._decoded_scalars = 0
        for index, buffer in enumerate(data.get("buffers", [])):
            uri = buffer.get("uri")
            if uri is None and binary:
                value = binary[0]
            elif isinstance(uri, str) and uri.startswith("data:") and ";base64," in uri:
                value = base64.b64decode(uri.split(",", 1)[1], validate=True)
            else:
                value = b""
                self.unavailable.append(f"buffer {index}: external URI not loaded (offline boundary)")
            if len(value) > MAX_BYTES or sum(map(len, self.buffers)) + len(value) > MAX_BYTES:
                raise ValueError("Decoded buffers exceed the analysis budget.")
            self.buffers.append(value)

    def values(self, index: int) -> List[Any]:
        if index in self._cache:
            return self._cache[index]
        accessors = self.data.get("accessors", [])
        if type(index) is not int or index < 0 or index >= len(accessors):
            raise ValueError("Invalid accessor reference.")
        accessor = accessors[index]
        count = accessor["count"]
        if type(count) is not int or count < 0 or count > MAX_SAMPLES:
            raise ValueError("Accessor exceeds the bounded sample budget.")
        dimensions = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}.get(accessor["type"])
        component = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}.get(accessor["componentType"])
        if not dimensions or not component:
            raise ValueError("Unsupported accessor type.")
        self._decoded_scalars += count * dimensions
        if self._decoded_scalars > 2000000:
            raise ValueError("Asset exceeds the cumulative decoded-scalar budget.")
        if "bufferView" not in accessor:
            result = apply_sparse(self.data, self.buffers, accessor, [0 if dimensions == 1 else [0] * dimensions for _ in range(count)])
            self._cache[index] = result
            return result
        view_index = accessor["bufferView"]
        views = self.data.get("bufferViews", [])
        if not isinstance(view_index, int) or view_index < 0 or view_index >= len(views):
            raise ValueError("Invalid buffer view.")
        view = views[view_index]
        buffer_index = view["buffer"]
        if not isinstance(buffer_index, int) or buffer_index < 0 or buffer_index >= len(self.buffers):
            raise ValueError("Invalid buffer reference.")
        buffer = self.buffers[buffer_index]
        if not buffer:
            self.unavailable.append(f"accessor {index}: buffer unavailable")
            return []
        fmt, size = component
        element_size = dimensions * size
        stride = int(view.get("byteStride", element_size))
        view_start, view_length = int(view.get("byteOffset", 0)), int(view["byteLength"])
        start = view_start + int(accessor.get("byteOffset", 0))
        end = start + (count - 1) * stride + element_size if count else start
        if stride < element_size or min(start, view_start, view_length) < 0 or end > min(len(buffer), view_start + view_length):
            raise ValueError("Accessor outside its buffer view.")
        result = []
        for row in range(count):
            values = list(struct.unpack_from("<" + fmt * dimensions, buffer, start + row * stride))
            if accessor.get("normalized") and accessor["componentType"] != 5126:
                bits = size * 8
                divisor = 2 ** (bits - 1) - 1 if fmt in {"b", "h"} else 2 ** bits - 1
                values = [max(-1, value / divisor) for value in values]
            if any(not math.isfinite(value) for value in values):
                raise ValueError("Accessor contains non-finite values.")
            result.append(values[0] if dimensions == 1 else values)
        result = apply_sparse(self.data, self.buffers, accessor, result)
        self._cache[index] = result
        return result


def parse_gltf(raw: Dict[str, Any], binary: List[bytes], name: str) -> CharacterDocument:
    if str(raw.get("asset", {}).get("version")) != "2.0":
        raise ValueError("Only glTF 2.0 is supported.")
    unsupported = set(raw.get("extensionsRequired", [])) & {"KHR_draco_mesh_compression", "EXT_meshopt_compression"}
    if unsupported:
        raise ValueError("Compressed geometry requires a decoder: " + ", ".join(sorted(unsupported)))
    accessor = Accessors(raw, binary)
    nodes, gltf_skins = raw.get("nodes", []), raw.get("skins", [])
    if len(nodes) > 10000:
        raise ValueError("Too many scene nodes.")
    parents = {}
    for index, node in enumerate(nodes):
        for child in node.get("children", []):
            if not isinstance(child, int) or child < 0 or child >= len(nodes) or child in parents:
                raise ValueError("Invalid or multiply parented scene node.")
            parents[child] = index
    # Validate the entire object tree, including non-skin nodes.
    for index in range(len(nodes)):
        seen, cursor = set(), index
        while cursor in parents:
            if cursor in seen:
                raise ValueError("Cyclic scene hierarchy.")
            seen.add(cursor)
            cursor = parents[cursor]
    joint_ids = {index for skin in gltf_skins for index in skin.get("joints", [])}
    if any(not isinstance(index, int) or index < 0 or index >= len(nodes) for index in joint_ids):
        raise ValueError("Invalid skin joint index.")
    joints = []
    inverse = {}
    for skin in gltf_skins:
        if "inverseBindMatrices" in skin:
            values = accessor.values(skin["inverseBindMatrices"])
            if values and len(values) != len(skin["joints"]):
                raise ValueError("Inverse bind matrix count mismatch.")
            for index, matrix in zip(skin["joints"], values):
                inverse.setdefault(index, matrix)
    for index in sorted(joint_ids):
        node = nodes[index]
        ancestor = parents.get(index)
        while ancestor is not None and ancestor not in joint_ids:
            ancestor = parents.get(ancestor)
        joints.append({"id": str(index), "name": node.get("name", f"joint-{index}"), "parent": str(ancestor) if ancestor is not None else None,
                       **{key: node[key] for key in ("translation", "rotation", "scale", "matrix") if key in node},
                       "inverse_bind_matrix": inverse.get(index), "metadata": {"node_index": index, "immediate_parent_node": parents.get(index), "transform_space": "local_to_source_parent"}})
    meshes, skins = [], []
    for node_index, node in enumerate(nodes):
        if "mesh" not in node:
            continue
        mesh_index = node["mesh"]
        source_mesh = _reference(raw.get("meshes", []), mesh_index, "mesh")
        for primitive_index, primitive in enumerate(source_mesh.get("primitives", [])):
            if primitive.get("extensions", {}).get("KHR_draco_mesh_compression"):
                raise ValueError("Draco primitive not supported.")
            attributes = primitive.get("attributes", {})
            if "POSITION" not in attributes:
                raise ValueError("Mesh primitive has no positions.")
            position_accessor = _reference(raw.get("accessors", []), attributes["POSITION"], "position accessor")
            vertex_count = int(position_accessor["count"])
            positions = accessor.values(attributes["POSITION"])
            indices = accessor.values(primitive["indices"]) if "indices" in primitive else list(range(vertex_count))
            mode = primitive.get("mode", 4)
            available_indices = "indices" not in primitive or bool(indices)
            faces = [indices[i:i+3] for i in range(0, len(indices), 3)] if mode == 4 and available_indices and len(indices) % 3 == 0 else None
            if mode != 4:
                accessor.unavailable.append(f"mesh {mesh_index}: topology metrics for primitive mode {mode} unavailable")
            mesh_id = f"node-{node_index}-primitive-{primitive_index}"
            skin_id = f"skin-{node_index}-{primitive_index}" if "skin" in node else None
            surface_attributes = {key: accessor.values(reference) or None for key, reference in attributes.items()
                                  if key.startswith(("TEXCOORD_", "COLOR_")) or key in {"NORMAL", "TANGENT"}}
            morph_data = [{key: accessor.values(reference) or None for key, reference in target.items()}
                          for target in primitive.get("targets", [])]
            for rows in list(surface_attributes.values()) + [v for target in morph_data for v in target.values()]:
                if rows is not None and len(rows) != vertex_count:
                    raise ValueError("Surface/morph accessor vertex count mismatch.")
            meshes.append({"id": mesh_id, "name": source_mesh.get("name", node.get("name", mesh_id)), "vertex_count": vertex_count,
                           "face_count": len(faces) if faces is not None else None, "positions": positions or None, "faces": faces,
                           "uv_maps": [key for key in attributes if key.startswith("TEXCOORD_")], "materials": [str(primitive["material"])] if "material" in primitive else [],
                           "normals": "NORMAL" in attributes, "tangents": "TANGENT" in attributes, "skin_id": skin_id,
                           "morph_targets": source_mesh.get("extras", {}).get("targetNames") or [f"target-{i}" for i, _ in enumerate(primitive.get("targets", []))],
                           "metadata": {"node_index": node_index, "primitive_mode": mode,
                                        "surface_vertex_attributes": surface_attributes,
                                        "morph_target_deltas": morph_data, "morph_space": "local_object_delta",
                                        "default_morph_weights": node.get("weights", source_mesh.get("weights", []))}})
            if skin_id:
                source_skin = _reference(gltf_skins, node["skin"], "skin")
                bone_ids = [str(index) for index in source_skin["joints"]]
                weights = None
                sets = sorted(key for key in attributes if key.startswith("JOINTS_"))
                if sets:
                    rows = [{} for _ in range(vertex_count)]
                    complete = True
                    for key in sets:
                        weight_key = key.replace("JOINTS", "WEIGHTS")
                        if weight_key not in attributes:
                            raise ValueError("Joint accessor has no matching weights.")
                        ji, wi = accessor.values(attributes[key]), accessor.values(attributes[weight_key])
                        if not ji or not wi:
                            complete = False
                            continue
                        if len(ji) != vertex_count or len(wi) != vertex_count:
                            raise ValueError("Influence accessor count mismatch.")
                        for row, identifiers, values in zip(rows, ji, wi):
                            for identifier, weight in zip(identifiers, values):
                                if not isinstance(identifier, int) or identifier < 0 or identifier >= len(bone_ids):
                                    raise ValueError("Invalid skin palette index.")
                                if weight:
                                    bone = bone_ids[identifier]
                                    row[bone] = row.get(bone, 0) + weight
                    if complete:
                        weights = rows
                skins.append({"id": skin_id, "mesh_id": mesh_id, "joints": bone_ids, "weights": weights})
    animations = []
    for index, animation in enumerate(raw.get("animations", [])):
        channels, duration = [], 0.0
        time_available = False
        for channel in animation.get("channels", []):
            sampler = _reference(animation.get("samplers", []), channel["sampler"], "animation sampler")
            times = accessor.values(sampler["input"])
            values = accessor.values(sampler["output"])
            if times:
                time_available = True
                duration = max(duration, max(times) - min(times))
            channels.append({"target": str(channel.get("target", {}).get("node", "")), "path": channel.get("target", {}).get("path"),
                             "interpolation": sampler.get("interpolation", "LINEAR"), "times": times, "values": values,
                             "keyframe_count": len(times), "values_available": bool(values)})
        animations.append({"id": str(index), "name": animation.get("name", f"clip-{index}"), "duration": duration if time_available else None, "channels": channels})
    return CharacterDocument.model_validate({"name": name, "coordinate_system": {"handedness": "right", "up_axis": "Y", "unit": "meter"},
        "joints": joints, "meshes": meshes, "skins": skins, "animations": animations,
        "materials": [{"id": str(index), **material} for index, material in enumerate(raw.get("materials", []))],
        "objects": [{"id": str(index), "parent": parents.get(index), **node} for index, node in enumerate(nodes)],
        "unavailable": sorted(set(accessor.unavailable + ["constraints/IK/FK controls: glTF does not preserve application rig controls"])),
        "metadata": {"source_format": "gltf2", "textures": raw.get("textures", []), "images": raw.get("images", [])}})


def parse_obj(text: str, name: str) -> Tuple[CharacterDocument, Dict[str, Any]]:
    positions, faces, groups, materials, uvs = [], [], [], [], 0
    for line in text.splitlines():
        parts = line.split()
        if not parts or parts[0].startswith("#"):
            continue
        if parts[0] == "v":
            positions.append([float(value) for value in parts[1:4]])
        elif parts[0] == "f":
            face = []
            for item in parts[1:]:
                index = int(item.split("/")[0])
                face.append(index - 1 if index > 0 else len(positions) + index)
            faces.append(face)
        elif parts[0] in {"o", "g"}:
            groups.append(" ".join(parts[1:]))
        elif parts[0] == "usemtl":
            materials.append(" ".join(parts[1:]))
        elif parts[0] == "vt":
            uvs += 1
        if len(positions) > MAX_SAMPLES or len(faces) > MAX_SAMPLES:
            raise ValueError("OBJ exceeds the analysis sample budget.")
    if not positions:
        raise ValueError("OBJ contains no geometry.")
    document = CharacterDocument.model_validate({"name": name, "meshes": [{"id": "mesh", "name": name,
        "vertex_count": len(positions), "face_count": len(faces), "positions": positions, "faces": faces,
        "materials": sorted(set(materials)), "uv_maps": ["obj-uv"] if uvs else [], "metadata": {"groups": groups}}],
        "unavailable": ["OBJ contains no rig, skinning or animation; external MTL files are not loaded."], "metadata": {"source_format": "obj"}})
    return document, {"groups": groups, "material_names": sorted(set(materials)), "uv_coordinate_count": uvs}
