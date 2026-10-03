"""Explicit bind-space conversion and bounded CPU linear-blend-skinning probes.

This is a reproducible stress harness, not a replacement for an application's
constraint solver, dual-quaternion skinning or an artist's deformation review.
"""
from __future__ import annotations

import math
from typing import Dict, List, Tuple

from app.expertise.schema import CharacterDocument

Vec = List[float]
IDENTITY = [1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.]


def sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def unit(a):
    length = math.sqrt(dot(a, a))
    if length < 1e-10:
        raise ValueError("Degenerate direction.")
    return [x / length for x in a]


def transform(matrix, point):
    if len(matrix) != 16 or not all(math.isfinite(x) for x in matrix):
        raise ValueError("Invalid bind transform.")
    if any(abs(matrix[i] - IDENTITY[i]) > 1e-7 for i in (12, 13, 14, 15)):
        raise ValueError("Bind transform must be affine row-major.")
    return [sum(matrix[row*4+i] * point[i] for i in range(3)) + matrix[row*4+3] for row in range(3)]


def binding(document: CharacterDocument) -> Tuple[Dict[str, Tuple[Vec, Vec]], Dict[str, List[Vec]]]:
    """Never guess whether glTF local transforms and mesh coordinates share a space."""
    objects = {obj.get("id"): obj for obj in document.objects}
    bones, meshes = {}, {}
    shared = document.metadata.get("deformation_space") == "shared_bind"
    blender = document.metadata.get("application") == "Blender"
    if not shared and not blender:
        raise ValueError("Pose testing needs explicit shared_bind landmarks or Blender rest-space extraction.")
    for joint in document.joints:
        metadata = joint.metadata
        head, tail = metadata.get("head"), metadata.get("tail")
        if not isinstance(head, list) or not isinstance(tail, list) or len(head) != 3 or len(tail) != 3:
            continue
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in head + tail):
            raise ValueError("Invalid bone landmark.")
        if blender:
            if metadata.get("transform_space") != "armature_rest":
                raise ValueError("Unsupported Blender bone space.")
            armature = objects.get(metadata.get("armature"), {})
            if "matrix_world" not in armature:
                raise ValueError("Missing armature world matrix.")
            head, tail = transform(armature["matrix_world"], head), transform(armature["matrix_world"], tail)
        if math.dist(head, tail) > 1e-8:
            bones[joint.id] = (head, tail)
    for mesh in document.meshes:
        if mesh.positions is None:
            continue
        if blender:
            obj = objects.get(mesh.id, {})
            if "matrix_world" not in obj:
                raise ValueError("Missing mesh world matrix.")
            meshes[mesh.id] = [transform(obj["matrix_world"], point) for point in mesh.positions]
        else:
            meshes[mesh.id] = mesh.positions
    return bones, meshes


def segment_distance(point, segment):
    head, tail = segment
    delta = sub(tail, head)
    ratio = max(0., min(1., dot(sub(point, head), delta) / max(1e-20, dot(delta, delta))))
    return math.dist(point, [head[i] + ratio*delta[i] for i in range(3)])


def edges(mesh):
    return sorted({tuple(sorted((face[index], face[(index+1) % len(face)]))) for face in (mesh.faces or []) for index in range(len(face))})


def rotate(point, pivot, axis, angle):
    value = sub(point, pivot)
    cosine, sine = math.cos(angle), math.sin(angle)
    perpendicular = cross(axis, value)
    along = dot(axis, value) * (1-cosine)
    return [pivot[i] + value[i]*cosine + perpendicular[i]*sine + axis[i]*along for i in range(3)]


def pose_point(point, weights, joint, descendants, bones, angle, axial=False):
    head, tail = bones[joint]
    direction = unit(sub(tail, head))
    axis = direction if axial else unit(cross(direction, [0., 0., 1.] if abs(direction[2]) < .9 else [1., 0., 0.]))
    turned = rotate(point, head, axis, angle)
    # All descendants inherit this one-joint probe. We do not invent IK/constraint behavior.
    active = sum(weight for key, weight in weights.items() if key in descendants)
    total = sum(weights.values())
    return [point[i]*(total-active) + turned[i]*active for i in range(3)] if total else list(point)
