"""Deterministic synthetic GLB writer (tests and the calibration fixture).

Produces small but structurally real glTF 2.0 binaries (box meshes, optional
skin, animation clips and FORM-style node names). These are SYNTHETIC assets:
they exercise the pipeline and give local calibration a known size; they say
nothing about the visual quality of real FORM characters.
"""

from __future__ import annotations

import hashlib
import json
import struct
from typing import Dict, List, Optional, Sequence


def _pad(data: bytes, fill: bytes = b"\x00") -> bytes:
    return data + fill * ((4 - len(data) % 4) % 4)


def form_name(source_id: str) -> str:
    return source_id[:36] + "-" + hashlib.sha256(source_id.encode()).hexdigest()[:16]


def build_glb(*, size: Sequence[float] = (0.5, 1.8, 0.3), center: Sequence[float] = (0.0, 0.9, 0.0),
              mesh_name: str = "body", skinned: bool = False, joint_count: int = 3,
              clips: Sequence[str] = (), hud_rings: int = 0, form_style: bool = False,
              required_extensions: Sequence[str] = (), omit_scene: bool = False,
              extra: Optional[Dict] = None) -> bytes:
    sx, sy, sz = (s / 2 for s in size)
    cx, cy, cz = center
    corners = [(cx + x * sx, cy + y * sy, cz + z * sz) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    faces = [0, 1, 3, 0, 3, 2, 4, 6, 7, 4, 7, 5, 0, 4, 5, 0, 5, 1, 2, 3, 7, 2, 7, 6, 0, 2, 6, 0, 6, 4, 1, 5, 7, 1, 7, 3]
    binary = bytearray()
    views: List[Dict] = []
    accessors: List[Dict] = []

    def add(data: bytes, accessor: Dict, target: Optional[int] = None) -> int:
        offset = len(binary)
        binary.extend(_pad(data))
        view = {"buffer": 0, "byteOffset": offset, "byteLength": len(data)}
        if target:
            view["target"] = target
        views.append(view)
        accessors.append({"bufferView": len(views) - 1, **accessor})
        return len(accessors) - 1

    positions = add(b"".join(struct.pack("<3f", *p) for p in corners), {
        "componentType": 5126, "count": 8, "type": "VEC3",
        "min": [min(p[i] for p in corners) for i in range(3)], "max": [max(p[i] for p in corners) for i in range(3)]}, 34962)
    indices = add(b"".join(struct.pack("<H", i) for i in faces), {"componentType": 5123, "count": len(faces), "type": "SCALAR"}, 34963)
    attributes = {"POSITION": positions}
    nodes: List[Dict] = []
    name = form_name(mesh_name) if form_style else mesh_name
    mesh_node = {"name": name, "mesh": 0}
    nodes.append(mesh_node)
    roots = [0]
    document: Dict = {"asset": {"version": "2.0", "generator": "akashi-spatial-test-builder"}}
    if skinned:
        attributes["JOINTS_0"] = add(bytes([0, 0, 0, 0] * 8), {"componentType": 5121, "count": 8, "type": "VEC4"}, 34962)
        attributes["WEIGHTS_0"] = add(b"".join(struct.pack("<4f", 1, 0, 0, 0) for _ in range(8)), {"componentType": 5126, "count": 8, "type": "VEC4"}, 34962)
        # Joint chain rests at y = 0.9, 1.2, 1.5, ...; inverse bind matrices undo each
        # joint's world translation so the bind pose equals the authored geometry.
        heights = [0.9 + 0.3 * j for j in range(joint_count)]
        inverse = add(b"".join(struct.pack("<16f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, -h, 0, 1) for h in heights),
                      {"componentType": 5126, "count": joint_count, "type": "MAT4"})
        first = len(nodes)
        for j in range(joint_count):
            joint = {"name": form_name(f"joint{j}") if form_style else f"joint{j}", "translation": [0, 0.3 if j else 0.9, 0]}
            if j + 1 < joint_count:
                joint["children"] = [first + j + 1]
            nodes.append(joint)
        mesh_node["skin"] = 0
        document["skins"] = [{"joints": list(range(first, first + joint_count)), "inverseBindMatrices": inverse}]
        roots.append(first)
    document["meshes"] = [{"name": mesh_name, "primitives": [{"attributes": attributes, "indices": indices}]}]
    if hud_rings:
        # HUD rings use their own static mesh (no joint attributes without a skin).
        document["meshes"].append({"name": "hud-ring", "primitives": [{"attributes": {"POSITION": positions}, "indices": indices}]})
    for ring in range(hud_rings):
        nodes.append({"name": form_name(f"hud-ring-{ring}"), "mesh": 1, "scale": [0.2, 0.02, 0.2], "translation": [0, 1.4 + ring * 0.05, 0]})
        roots.append(len(nodes) - 1)
    animations = []
    for clip_number, clip in enumerate(clips):
        times = add(struct.pack("<3f", 0.0, 0.5, 1.0 + clip_number), {"componentType": 5126, "count": 3, "type": "SCALAR", "min": [0.0], "max": [1.0 + clip_number]})
        values = add(struct.pack("<12f", 0, 0, 0, 1, 0, 0.383, 0, 0.924, 0, 0, 0, 1), {"componentType": 5126, "count": 3, "type": "VEC4"})
        target = len(nodes) - 1 if not skinned else roots[1]
        animations.append({"name": clip, "samplers": [{"input": times, "output": values}],
                           "channels": [{"sampler": 0, "target": {"node": target, "path": "rotation"}}]})
    if animations:
        document["animations"] = animations
    document.update({"nodes": nodes, "bufferViews": views, "accessors": accessors,
                     "buffers": [{"byteLength": len(binary)}]})
    if not omit_scene:
        document.update({"scenes": [{"nodes": roots}], "scene": 0})
    if required_extensions:
        document["extensionsUsed"] = list(required_extensions)
        document["extensionsRequired"] = list(required_extensions)
    if extra:
        document.update(extra)
    payload = _pad(json.dumps(document, separators=(",", ":")).encode(), b" ")
    bin_chunk = bytes(binary)
    total = 12 + 8 + len(payload) + 8 + len(bin_chunk)
    return (struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<I4s", len(payload), b"JSON") + payload
            + struct.pack("<I4s", len(bin_chunk), b"BIN\x00") + bin_chunk)


CALIBRATION_LABEL = "Calibration block 1.70 m (synthetic)"


def calibration_fixture() -> bytes:
    """A 0.50 x 1.70 x 0.30 m skinned block with one clip, for camera/scale calibration."""
    return build_glb(size=(0.5, 1.7, 0.3), center=(0.0, 0.85, 0.0), mesh_name="calibration-block",
                     skinned=True, joint_count=3, clips=("Calibration Sway",))
