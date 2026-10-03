"""Local quad-loft authoring. Segmented shells are explicit, not seamless retopology."""

import math
import random
from .contracts import Design, CandidateSpec, validate_colors, VERSION
from app.expertise.workshop.geometry import segment_distance


def construct(design, method=None, seed=57):
    d = validate_colors(Design.model_validate(design))
    m = CandidateSpec.model_validate(method or {})
    rng = random.Random(seed)
    h, n = d.height, m.radial
    joints, meshes, skins = [], [], []
    scale = {"slender": 0.85, "balanced": 1.0, "strong": 1.2}[d.build]
    width = h * d.shoulder_ratio / 2

    def joint(key, parent, a, b):
        joints.append(
            {
                "id": key,
                "name": key,
                "parent": parent,
                "metadata": {"head": a, "tail": b, "deform": True},
            }
        )

    joint("root", None, [0, 0, 0], [0, 0, h * 0.06])
    joint("pelvis", "root", [0, 0, h * 0.49], [0, 0, h * 0.55])
    joint("spine", "pelvis", [0, 0, h * 0.55], [0, 0, h * 0.65])
    joint("chest", "spine", [0, 0, h * 0.65], [0, 0, h * 0.78])
    neck_base = min(0.78, 1 - d.head_ratio - 0.03)
    joint("neck", "chest", [0, 0, h * neck_base], [0, 0, h * (1 - d.head_ratio)])
    joint("head", "neck", [0, 0, h * (1 - d.head_ratio)], [0, 0, h])
    joint(
        "jaw",
        "head",
        [0, -h * 0.038, h * (1 - d.head_ratio * 0.89)],
        [0, -h * 0.055, h * (1 - d.head_ratio)],
    )
    for sign, side in ((1, "L"), (-1, "R")):
        x = sign * width
        a, b, c = (
            [x * 0.8, 0, h * 0.77],
            [x * 1.8, 0, h * 0.65],
            [x * 2.65, 0, h * 0.54],
        )
        joint("clavicle_" + side, "chest", [0, 0, h * 0.76], a)
        joint("upper_arm_" + side, "clavicle_" + side, a, b)
        joint("forearm_" + side, "upper_arm_" + side, b, c)
        joint(
            "forearm_twist_" + side,
            "forearm_" + side,
            [b[k] * 0.6 + c[k] * 0.4 for k in range(3)],
            [b[k] * 0.2 + c[k] * 0.8 for k in range(3)],
        )
        end = [c[0] + sign * h * 0.055, 0, c[2] - h * 0.035]
        joint("hand_" + side, "forearm_" + side, c, end)
        for i, finger in enumerate(("thumb", "index", "middle", "ring", "little")):
            start = [end[0] - sign * h * 0.018, (i - 2) * h * 0.012, end[2]]
            for seg in range(3):
                tail = [
                    start[0] + sign * h * (0.017 if finger != "thumb" else 0.013),
                    start[1],
                    start[2] - h * 0.009,
                ]
                joint(
                    finger + str(seg) + "_" + side,
                    "hand_" + side if seg == 0 else finger + str(seg - 1) + "_" + side,
                    start,
                    tail,
                )
                start = tail
        hip, knee, ankle = (
            [sign * h * 0.07, 0, h * 0.5],
            [sign * h * 0.072, -h * 0.006, h * 0.275],
            [sign * h * 0.073, 0, h * 0.065],
        )
        joint("thigh_" + side, "pelvis", hip, knee)
        joint("shin_" + side, "thigh_" + side, knee, ankle)
        joint("foot_" + side, "shin_" + side, ankle, [ankle[0], -h * 0.085, h * 0.035])
        joint(
            "toe_" + side,
            "foot_" + side,
            [ankle[0], -h * 0.085, h * 0.035],
            [ankle[0], -h * 0.115, h * 0.03],
        )
        joint(
            "eye_" + side,
            "head",
            [sign * h * 0.027, -h * 0.052, h * (1 - d.head_ratio * 0.46)],
            [sign * h * 0.027, -h * 0.065, h * (1 - d.head_ratio * 0.46)],
        )
    bone = {j["id"]: j for j in joints}

    def face_z(fraction):
        return h * (1 - d.head_ratio + d.head_ratio * fraction)

    def surface(key, centers, radii, palette, material, family, cap=True):
        points, faces = [], []
        for i, (center, (rx, ry)) in enumerate(zip(centers, radii)):
            before, after = (
                centers[max(0, i - 1)],
                centers[min(len(centers) - 1, i + 1)],
            )
            delta = [after[k] - before[k] for k in range(3)]
            length = math.sqrt(sum(v * v for v in delta))
            axis = [v / length for v in delta]
            ref = [0, 1, 0] if abs(axis[1]) < 0.8 else [1, 0, 0]
            u = [
                axis[1] * ref[2] - axis[2] * ref[1],
                axis[2] * ref[0] - axis[0] * ref[2],
                axis[0] * ref[1] - axis[1] * ref[0],
            ]
            ul = math.sqrt(sum(v * v for v in u))
            u = [v / ul for v in u]
            v = [
                axis[1] * u[2] - axis[2] * u[1],
                axis[2] * u[0] - axis[0] * u[2],
                axis[0] * u[1] - axis[1] * u[0],
            ]
            for s in range(n):
                theta = 2 * math.pi * s / n
                points.append(
                    [
                        center[k]
                        + rx * u[k] * math.cos(theta)
                        + ry * v[k] * math.sin(theta)
                        for k in range(3)
                    ]
                )
        for r in range(len(centers) - 1):
            for s in range(n):
                faces.append(
                    [
                        r * n + s,
                        r * n + (s + 1) % n,
                        (r + 1) * n + (s + 1) % n,
                        (r + 1) * n + s,
                    ]
                )
        if cap:
            # Explicit cap triangles; no degenerate collapsed ring or giant ngon.
            for r, reverse in ((0, True), (len(centers) - 1, False)):
                index = len(points)
                points.append(centers[r])
                for s in range(n):
                    f = [index, r * n + s, r * n + (s + 1) % n]
                    faces.append(f[::-1] if reverse else f)
        weights = []
        for p in points:
            distances = {
                k: max(
                    1e-5,
                    segment_distance(
                        p, (bone[k]["metadata"]["head"], bone[k]["metadata"]["tail"])
                    ),
                )
                for k in palette
            }
            raw = {
                k: (min(distances.values()) / v) ** m.distance_power
                for k, v in distances.items()
            }
            weights.append({k: v / sum(raw.values()) for k, v in raw.items()})
        uv = []
        for f in faces:
            # Face-local seams preserve actual loop correspondence, not invented UV names.
            uv.extend(
                [
                    [0.5, 0.5]
                    if i >= len(centers) * n
                    else [(i % n) / n, min(1, (i // n) / (len(centers) - 1))]
                    for i in f
                ]
            )
        sid = "skin:" + key
        meshes.append(
            {
                "id": key,
                "name": key,
                "vertex_count": len(points),
                "positions": points,
                "faces": faces,
                "skin_id": sid,
                "uv_maps": ["UVMap"],
                "materials": [material],
                "metadata": {"family": family, "uv_coordinates": {"UVMap": uv}},
            }
        )
        skins.append({"id": sid, "mesh_id": key, "joints": palette, "weights": weights})

    def ellipsoid(key, center, size, palette, mat, family):
        rings = 9
        zs = [-1 + i * 2 / (rings - 1) for i in range(rings)]
        surface(
            key,
            [[center[0], center[1], center[2] + z * size[2]] for z in zs],
            [
                (
                    max(0.035, math.sqrt(max(0, 1 - z * z))) * size[0],
                    max(0.035, math.sqrt(max(0, 1 - z * z))) * size[1],
                )
                for z in zs
            ],
            palette,
            mat,
            family,
        )

    torso_z = [0.48, 0.53, 0.59, 0.66, 0.73, 0.78, 0.80]
    rx = [
        0.09,
        0.10,
        0.075,
        0.085,
        d.shoulder_ratio * 0.40,
        d.shoulder_ratio * 0.42,
        0.035,
    ]
    ry = [0.055, 0.065, 0.046, 0.06, 0.075, 0.065, 0.035]
    surface(
        "body-torso",
        [[0, 0, h * z] for z in torso_z],
        [(h * x * scale, h * y * scale) for x, y in zip(rx, ry)],
        ["pelvis", "spine", "chest", "neck"],
        "skin",
        "body",
    )
    surface(
        "body-neck",
        [[0, 0, h * neck_base], [0, 0, h * (1 - d.head_ratio + 0.015)]],
        [(h * 0.033, h * 0.033), (h * 0.031, h * 0.031)],
        ["neck", "head"],
        "skin",
        "body",
    )
    if d.appearance == "atelier":
        from .appearance import face, hair, tailoring

        face(d, surface, ellipsoid)
    else:
        ellipsoid(
            "body-head",
            [0, -h * 0.005, h * (1 - d.head_ratio / 2)],
            [h * 0.065, h * 0.055, h * d.head_ratio / 2],
            ["head"],
            "skin",
            "face",
        )
    if d.appearance == "classic":
        ellipsoid(
            "nose",
            [0, -h * 0.059, face_z(0.42)],
            [h * 0.012, h * 0.018, h * 0.023],
            ["head"],
            "skin",
            "face_detail",
        )
    for side, sign in (("L", 1), ("R", -1)):
        if d.appearance == "classic":
            ellipsoid(
                "ear-" + side,
                [sign * h * 0.064, 0, face_z(0.48)],
                [h * 0.012, h * 0.011, h * 0.024],
                ["head"],
                "skin",
                "face_detail",
            )
            ellipsoid(
                "eye-" + side,
                [sign * h * 0.027, -h * 0.051, face_z(0.54)],
                [h * 0.021, h * 0.012, h * 0.011],
                ["eye_" + side],
                "eye_white",
                "eye",
            )
            ellipsoid(
                "iris-" + side,
                [sign * h * 0.027, -h * 0.062, face_z(0.54)],
                [h * 0.008, h * 0.003, h * 0.008],
                ["eye_" + side],
                "accent",
                "eye",
            )
            ellipsoid(
                "brow-" + side,
                [sign * h * 0.027, -h * 0.052, face_z(0.67)],
                [h * 0.023, h * 0.004, h * 0.003],
                ["head"],
                "hair",
                "face_detail",
            )
        for part, radius in (
            ("upper_arm", 0.037),
            ("forearm", 0.028),
            ("thigh", 0.056),
            ("shin", 0.036),
        ):
            j = bone[part + "_" + side]
            a, b = j["metadata"]["head"], j["metadata"]["tail"]
            centers = [
                [a[k] * (1 - t) + b[k] * t for k in range(3)]
                for t in (0, 0.15, 0.35, 0.55, 0.75, 1)
            ]
            radii = [
                (h * radius * scale * f, h * radius * scale * f * 0.9)
                for f in (0.8, 1, 1, 0.95, 0.8, 0.65)
            ]
            palette = [j["id"]] + ([j["parent"]] if j["parent"] else [])
            surface("body-" + j["id"], centers, radii, palette, "skin", "body")
            if part in ("upper_arm", "forearm", "thigh", "shin"):
                surface(
                    "garment-" + j["id"],
                    centers,
                    [(x + m.clearance, y + m.clearance) for x, y in radii],
                    palette,
                    "cloth",
                    "clothing",
                )
        j = bone["hand_" + side]
        a, b = j["metadata"]["head"], j["metadata"]["tail"]
        ellipsoid(
            "palm-" + side,
            [(a[k] + b[k]) / 2 for k in range(3)],
            [h * 0.040, h * 0.030, h * 0.025],
            ["hand_" + side],
            "skin",
            "hand",
        )
        for finger in ("thumb", "index", "middle", "ring", "little"):
            keys = [finger + str(seg) + "_" + side for seg in range(3)]
            centers = [bone[k]["metadata"]["head"] for k in keys] + [
                bone[keys[-1]]["metadata"]["tail"]
            ]
            surface(
                finger + "-" + side,
                centers,
                [
                    (h * 0.007 * (1 - i * 0.1), h * 0.007 * (1 - i * 0.1))
                    for i in range(4)
                ],
                keys,
                "skin",
                "finger",
            )
        ellipsoid(
            "boot-" + side,
            [sign * h * 0.073, -h * 0.045, h * 0.050],
            [h * 0.046, h * 0.086, h * 0.049],
            ["foot_" + side, "toe_" + side],
            "cloth",
            "foot",
        )
    surface(
        "garment-torso",
        [[0, 0, h * z] for z in torso_z],
        [
            (h * x * scale + m.clearance, h * y * scale + m.clearance)
            for x, y in zip(rx, ry)
        ],
        ["pelvis", "spine", "chest", "neck"],
        "cloth",
        "clothing",
    )
    if d.clothing == "coat":
        surface(
            "coat-skirt",
            [[0, 0.01 * h, h * z] for z in (0.32, 0.38, 0.45, 0.51, 0.54)],
            [
                (h * x, h * y)
                for x, y in (
                    (0.14, 0.08),
                    (0.13, 0.077),
                    (0.12, 0.073),
                    (0.108, 0.072),
                    (0.105, 0.068),
                )
            ],
            ["pelvis", "spine"],
            "cloth",
            "clothing",
            cap=False,
        )
    if d.clothing == "armor":
        for sign, side in ((1, "L"), (-1, "R")):
            ellipsoid(
                "pauldron-" + side,
                [sign * width * 0.92, 0, h * 0.77],
                [h * 0.065, h * 0.075, h * 0.047],
                ["clavicle_" + side],
                "metal",
                "accessory",
            )
    ellipsoid(
        "belt-buckle",
        [0, -h * 0.080, h * 0.52],
        [h * 0.025, h * 0.01, h * 0.019],
        ["pelvis"],
        "metal",
        "accessory",
    )
    if d.appearance == "atelier":
        hair(d, surface, ellipsoid, rng)
        tailoring(d, surface, ellipsoid, m.clearance)
    if d.hair != "none" and d.appearance == "classic":
        # Curved tapered strands, not a recolored background or a baked facial mask.
        for i in range(20):
            phi = 2 * math.pi * i / 20
            length = h * (0.095 if d.hair == "short" else 0.23) * rng.uniform(0.85, 1.1)
            centers = []
            for t in (0, 0.25, 0.5, 0.75, 1):
                radius = h * (0.015 + 0.06 * math.sin(t * 1.4))
                centers.append(
                    [
                        radius * math.cos(phi),
                        h * 0.009 + radius * math.sin(phi),
                        h * 1.005 - t * length,
                    ]
                )
            surface(
                "hair-lock-%02d" % i,
                centers,
                [(h * 0.015 * f, h * 0.009 * f) for f in (1, 1, 0.9, 0.6, 0.08)],
                ["head"],
                "hair",
                "hair",
            )
    if d.appearance == "classic":
        ellipsoid(
            "mouth",
            [0, -h * 0.057, face_z(0.25)],
            [h * 0.024, h * 0.005, h * 0.005],
            ["jaw", "head"],
            "lip",
            "face_detail",
        )
    if d.hud:
        # Torus segments embedded in the character rig; never baked into body geometry.
        for ring in range(3):
            centers = []
            radius = h * (0.19 + ring * 0.025)
            for i in range(33):
                angle = 2 * math.pi * i / 32
                centers.append(
                    [
                        radius * math.cos(angle),
                        h * 0.08 + ring * 0.025,
                        h * 0.84 + radius * math.sin(angle),
                    ]
                )
            surface(
                "hud-ring-" + str(ring),
                centers,
                [(h * 0.0015, h * 0.0015)] * 33,
                ["chest"],
                "energy",
                "hud",
                cap=False,
            )
    colors = {
        "skin": d.skin_color,
        "cloth": d.cloth_color,
        "accent": d.accent_color,
        "energy": d.accent_color,
        "metal": [0.20, 0.23, 0.28],
        "hair": [0.018, 0.013, 0.015],
        "eye_white": [0.75, 0.77, 0.73],
        "lip": [0.25, 0.08, 0.07],
        "pupil": [0.005, 0.006, 0.008],
        "lining": [min(1, c * 1.8 + 0.025) for c in d.cloth_color],
    }
    return {
        "schema_version": 1,
        "name": "AKASHI Procedural Character",
        "coordinate_system": {"up_axis": "Z", "unit_scale": 1},
        "joints": joints,
        "meshes": meshes,
        "skins": skins,
        "materials": [
            {"id": k, "name": k, "diffuse_color": v + [1]} for k, v in colors.items()
        ],
        "animations": [],
        "metadata": {
            "synthetic": True,
            "deformation_space": "shared_bind",
            "production_version": VERSION,
            "appearance_version": "atelier-2"
            if d.appearance == "atelier"
            else "classic-1",
            "production_design": d.model_dump(),
            "production_method": m.model_dump(),
            "seed": seed,
            "limitations": [
                "Quad-loft segmented shells; not seamless anatomical retopology.",
                "Clothing is skinned shell authoring, not cloth simulation.",
                "No reference-fidelity certification without independent reference evidence.",
            ],
        },
    }
