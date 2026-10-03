"""Computed authoring evidence; no invented perceptual/artist scores."""

import math
from collections import Counter


def evaluate(document):
    edges, quads, faces, degenerate, boundary, nonmanifold, vertices = (
        0,
        0,
        0,
        0,
        0,
        0,
        0,
    )
    for mesh in document["meshes"]:
        counts = Counter()
        p = mesh["positions"]
        vertices += len(p)
        for f in mesh["faces"]:
            faces += 1
            quads += int(len(f) == 4)
            for a, b in zip(f, f[1:] + f[:1]):
                counts[tuple(sorted((a, b)))] += 1
            a, b, c = [p[i] for i in f[:3]]
            u = [b[k] - a[k] for k in range(3)]
            v = [c[k] - a[k] for k in range(3)]
            cross = [
                u[1] * v[2] - u[2] * v[1],
                u[2] * v[0] - u[0] * v[2],
                u[0] * v[1] - u[1] * v[0],
            ]
            degenerate += int(sum(x * x for x in cross) < 1e-18)
        edges += len(counts)
        nonmanifold += sum(v > 2 for v in counts.values())
        if mesh["metadata"]["family"] not in {"hud", "clothing"}:
            boundary += sum(v == 1 for v in counts.values())
    normal = max(
        abs(sum(w.values()) - 1) for s in document["skins"] for w in s["weights"]
    )
    method = document["metadata"]["production_method"]
    chord = 1 - math.cos(math.pi / method["radial"])
    clearance = method["clearance"]
    defects = []
    if degenerate:
        defects.append("degenerate_faces")
    if boundary or nonmanifold:
        defects.append("unexpected_surface_boundaries")
    if normal > 1e-6:
        defects.append("weight_normalization")
    if chord > 0.025:
        defects.append("insufficient_radial_resolution")
    if clearance < 0.009:
        defects.append("insufficient_declared_garment_clearance")
    loss = (
        chord
        + max(0, 0.009 - clearance) * 10
        + degenerate
        + boundary
        + nonmanifold
        + normal
    )
    return {
        "passed": not defects,
        "loss": loss,
        "defects": defects,
        "vertices": vertices,
        "faces": faces,
        "edges": edges,
        "quad_ratio": quads / max(1, faces),
        "degenerate_faces": degenerate,
        "unexpected_boundary_edges": boundary,
        "nonmanifold_edges": nonmanifold,
        "normalization_max_error": normal,
        "radial_chord_error": chord,
        "declared_clearance": clearance,
        "visual_fidelity": "unmeasured",
        "scope": "procedural authoring metrics; not seamless topology, cloth collision or artistic certification",
    }
