"""Locally authored stylized forms. Anatomical proposals, not recovered source truth.

Uses the same canonical loft/UV/skinning authoring port as the original rig.
No DCC-dependent topology changes and no model-generated executable code.
"""

import math


def face(d, surface, ellipsoid):
    h, r = d.height, d.head_ratio

    def z(t):
        return h * (1 - r + r * t)

    # Chin -> jaw -> cheek -> temple -> cranial vault: deliberate silhouette.
    profile = [
        (0, 0.024, 0.022),
        (0.07, 0.033, 0.034),
        (0.17, 0.045, 0.040),
        (0.30, 0.051, 0.043),
        (0.43, 0.056, 0.047),
        (0.55, 0.057, 0.050),
        (0.67, 0.054, 0.051),
        (0.80, 0.053, 0.050),
        (0.92, 0.039, 0.041),
        (1, 0.012, 0.016),
    ]
    surface(
        "body-head",
        [[0, h * (0.006 if t < 0.3 else 0), z(t)] for t, _, _ in profile],
        [(h * x, h * y) for _, x, y in profile],
        ["head"],
        "skin",
        "face",
    )
    # A small bridge/tip, lips and eyelid rims rather than protruding eyeballs.
    surface(
        "nose",
        [
            [0, -h * y, z(t)]
            for t, y in ((0.36, 0.047), (0.40, 0.061), (0.46, 0.057), (0.59, 0.046))
        ],
        [
            (h * x, h * y)
            for x, y in ((0.009, 0.006), (0.008, 0.007), (0.005, 0.006), (0.004, 0.003))
        ],
        ["head"],
        "skin",
        "face_detail",
    )
    for name, t, width, depth in (
        ("upper-lip", 0.265, 0.017, 0.003),
        ("lower-lip", 0.225, 0.016, 0.004),
    ):
        ellipsoid(
            name,
            [0, -h * 0.043, z(t)],
            [h * width, h * depth, h * 0.0025],
            ["jaw", "head"],
            "lip",
            "face_detail",
        )
    for side, sign in (("L", 1), ("R", -1)):
        ellipsoid(
            "ear-" + side,
            [sign * h * 0.056, h * 0.003, z(0.47)],
            [h * 0.008, h * 0.006, h * 0.017],
            ["head"],
            "skin",
            "face_detail",
        )
        ellipsoid(
            "eye-" + side,
            [sign * h * 0.023, -h * 0.045, z(0.56)],
            [h * 0.012, h * 0.006, h * 0.006],
            ["eye_" + side],
            "eye_white",
            "eye",
        )
        ellipsoid(
            "iris-" + side,
            [sign * h * 0.023, -h * 0.0505, z(0.56)],
            [h * 0.004, h * 0.0015, h * 0.004],
            ["eye_" + side],
            "accent",
            "eye",
        )
        ellipsoid(
            "pupil-" + side,
            [sign * h * 0.023, -h * 0.052, z(0.56)],
            [h * 0.002, h * 0.001, h * 0.003],
            ["eye_" + side],
            "pupil",
            "eye",
        )
        for upper in (False, True):
            centers = []
            for i in range(9):
                angle = math.pi * i / 8
                centers.append(
                    [
                        sign * h * 0.023 + h * 0.012 * math.cos(angle),
                        -h * (0.047 + 0.003 * math.sin(angle)),
                        z(0.56) + h * 0.006 * math.sin(angle) * (1 if upper else -1),
                    ]
                )
            surface(
                f"lid-{side}-{upper}",
                centers,
                [(h * 0.0015, h * 0.0015)] * 9,
                ["head"],
                "skin",
                "face_detail",
            )
        surface(
            "brow-" + side,
            [
                [sign * h * x, -h * y, z(t)]
                for x, y, t in (
                    (0.010, 0.047, 0.67),
                    (0.023, 0.049, 0.685),
                    (0.037, 0.040, 0.67),
                )
            ],
            [(h * 0.002, h * 0.0015)] * 3,
            ["head"],
            "hair",
            "face_detail",
        )


def hair(d, surface, ellipsoid, rng):
    if d.hair == "none":
        return
    h, r = d.height, d.head_ratio
    # Scalp cap stops above the eyes. Long locks occupy the sides/back, not the beard region.
    surface(
        "hair-scalp",
        [[0, h * 0.004, h * (1 - r + r * t)] for t in (0.70, 0.78, 0.88, 0.96, 1.025)],
        [
            (h * x, h * y)
            for x, y in (
                (0.057, 0.053),
                (0.058, 0.054),
                (0.049, 0.050),
                (0.032, 0.037),
                (0.007, 0.008),
            )
        ],
        ["head"],
        "hair",
        "hair",
    )
    for i in range(28):
        # From left temple through the back to right temple; no long front locks.
        phi = -0.12 + (math.pi + 0.24) * i / 27
        x, y = math.cos(phi), math.sin(phi)
        length = h * (0.065 if d.hair == "short" else 0.17) * rng.uniform(0.85, 1.08)
        centers = [
            [
                h * x * (0.044 + 0.019 * t),
                h * (0.008 + y * (0.040 + 0.021 * t)),
                h * (1 - r * 0.18) - length * t,
            ]
            for t in (0, 0.2, 0.45, 0.7, 1)
        ]
        surface(
            "hair-lock-%02d" % i,
            centers,
            [(h * 0.009 * f, h * 0.005 * f) for f in (0.65, 1, 0.85, 0.5, 0.045)],
            ["head"],
            "hair",
            "hair",
        )
    for i in range(9):
        x = (i - 4) * 0.010
        depth = rng.uniform(0.22, 0.37)
        sweep = rng.uniform(0.005, 0.018)
        centers = [
            [
                h * (x + sweep * t),
                -h * (0.018 + 0.035 * t),
                h * (1.005 - r * (0.02 + depth * t)),
            ]
            for t in (0, 0.25, 0.55, 0.8, 1)
        ]
        surface(
            "fringe-%02d" % i,
            centers,
            [(h * 0.010 * f, h * 0.004 * f) for f in (0.8, 1, 0.9, 0.5, 0.04)],
            ["head"],
            "hair",
            "hair",
        )


def tailoring(d, surface, ellipsoid, clearance):
    h = d.height
    if d.clothing in {"coat", "armor"}:
        for side, sign in (("L", 1), ("R", -1)):
            # Flattened curved lapel, seams and closures; separate skinned layers.
            surface(
                "lapel-" + side,
                [
                    [sign * h * x, -h * y - clearance, h * z]
                    for x, y, z in (
                        (0.036, 0.060, 0.78),
                        (0.080, 0.082, 0.73),
                        (0.054, 0.068, 0.67),
                        (0.015, 0.060, 0.59),
                    )
                ],
                [
                    (h * 0.021, h * 0.004),
                    (h * 0.026, h * 0.004),
                    (h * 0.016, h * 0.003),
                    (h * 0.004, h * 0.002),
                ],
                ["chest", "spine"],
                "lining",
                "clothing",
            )
            surface(
                "seam-" + side,
                [
                    [sign * h * x, -h * y - clearance - 0.002, h * z]
                    for x, y, z in (
                        (0.034, 0.06, 0.77),
                        (0.077, 0.08, 0.73),
                        (0.052, 0.067, 0.67),
                        (0.016, 0.06, 0.59),
                    )
                ],
                [(h * 0.0012, h * 0.0012)] * 4,
                ["chest", "spine"],
                "accent",
                "clothing",
            )
            ellipsoid(
                "pocket-" + side,
                [sign * h * 0.07, -h * 0.075 - clearance, h * 0.58],
                [h * 0.029, h * 0.003, h * 0.012],
                ["spine"],
                "lining",
                "clothing",
            )
    for i in range(4):
        ellipsoid(
            "closure-%d" % i,
            [0, -h * 0.080 - clearance, h * (0.56 + i * 0.035)],
            [h * 0.0035, h * 0.002, h * 0.0035],
            ["spine", "chest"],
            "metal",
            "accessory",
        )
    # Sole layers give the footwear a readable silhouette.
    for side, sign in (("L", 1), ("R", -1)):
        ellipsoid(
            "sole-" + side,
            [sign * h * 0.073, -h * 0.045, h * 0.016],
            [h * 0.047, h * 0.087, h * 0.010],
            ["foot_" + side, "toe_" + side],
            "lining",
            "foot",
        )
