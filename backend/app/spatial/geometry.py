"""Small, dependency-free vector/quaternion helpers for scene commands.

Conventions follow glTF/three.js: right-handed, +Y up, the default camera looks
toward -Z, units are metres. Quaternions are ``[x, y, z, w]``. Every value that
enters the scene document is quantised so digests are platform-stable.
"""

from __future__ import annotations

import math
from typing import List, Sequence

from app.history.canonical import quantize

Vec3 = List[float]
Quat = List[float]

IDENTITY: Quat = [0.0, 0.0, 0.0, 1.0]
AXES = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}


def q3(values: Sequence[float]) -> Vec3:
    return [quantize(float(v)) for v in values]


def canonical_quat(q: Sequence[float]) -> Quat:
    x, y, z, w = (float(v) for v in q)
    length = math.sqrt(x * x + y * y + z * z + w * w)
    if not math.isfinite(length) or length < 1e-9:
        raise ValueError("Rotation quaternion is degenerate.")
    x, y, z, w = x / length, y / length, z / length, w / length
    # q and -q are the same rotation; pick one sign so digests are stable.
    for component in (w, x, y, z):
        if abs(component) > 1e-12:
            if component < 0:
                x, y, z, w = -x, -y, -z, -w
            break
    return [quantize(x), quantize(y), quantize(z), quantize(w)]


def axis_angle(axis: str, degrees: float) -> Quat:
    if axis not in AXES:
        raise ValueError("Rotation axis must be x, y or z.")
    ax, ay, az = AXES[axis]
    half = math.radians(float(degrees)) / 2
    s = math.sin(half)
    return [ax * s, ay * s, az * s, math.cos(half)]


def multiply(a: Sequence[float], b: Sequence[float]) -> Quat:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return [
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    ]


def rotate_world(rotation: Sequence[float], axis: str, degrees: float) -> Quat:
    """Apply a world-space rotation after the existing orientation."""
    return canonical_quat(multiply(axis_angle(axis, degrees), rotation))


def yaw_degrees(rotation: Sequence[float]) -> float:
    x, y, z, w = rotation
    siny = 2 * (w * y + x * z)
    cosy = 1 - 2 * (y * y + x * x)
    return quantize(math.degrees(math.atan2(siny, cosy)), 3)


def finite(values: Sequence[float]) -> bool:
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values)
