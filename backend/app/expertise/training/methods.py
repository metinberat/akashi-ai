"""Typed workflow compiler. No generated scripts or retrieved prose are executed."""
import math

from app.expertise.schema import CharacterDocument
from app.expertise.workshop.contracts import Landmark, Recipe
from app.expertise.workshop.operations import apply
from app.expertise.workshop.repository import digest
from .contracts import MethodSpec


def method_id(spec):
    return "method-" + digest(spec)[:32]


def catalog(reconstruct=False, recipes=()):
    prior = max((m.get("max_influences", 2) for r in recipes for m in r["patterns"]["skin_metrics"]), default=2)
    # Inference from observed source influence limits is only a prior, not a quality assertion.
    values = [MethodSpec(binding="preserve", reconstruct=reconstruct)]
    for binding in ("segmented", "spatial"):
        for power in (1., 2., 3., 4.):
            values.append(MethodSpec(binding=binding, reconstruct=reconstruct, distance_power=power, max_influences=min(8, max(2, prior))))
    values += [MethodSpec(binding="segmented", reconstruct=reconstruct, distance_power=2, smoothing=v) for v in (.1, .3)]
    return [{"id": method_id(v.model_dump()), "spec": v.model_dump(), "workflow": ["inspect_inputs", "estimate_landmarks" if reconstruct else "preserve_rest",
            "normalize", v.binding, "smooth" if v.smoothing else "preserve_adjacency", "held_out_pose_evaluation"],
            "preconditions": ["explicit bind space", "complete geometry", "region labels for segmented construction"],
            "scope": "synthetic segmented geometry; real-target application requires independent validation"} for v in values]


def estimate_landmarks(document):
    """Principal-axis segments from target geometry; no access to reference joints."""
    regions = document.metadata.get("practice_descriptor", {}).get("regions", [])
    if not document.metadata.get("synthetic") or not regions:
        raise ValueError("Automatic anatomical reconstruction is limited to labelled synthetic exercises.")
    meshes = {m.id: m for m in document.meshes}
    landmarks, seen = [], set()
    for region in regions:
        if region["joint"] in seen:
            continue
        seen.add(region["joint"])
        mesh = meshes[region["mesh"]]
        if not mesh.positions:
            raise ValueError("Landmark estimation requires target geometry.")
        center = [sum(p[k] for p in mesh.positions)/len(mesh.positions) for k in range(3)]
        covariance = [[sum((p[i]-center[i])*(p[j]-center[j]) for p in mesh.positions) for j in range(3)] for i in range(3)]
        direction = list(mesh.metadata.get("orientation_hint", [1., 1., 1.]))
        for _ in range(32):
            vector = [sum(covariance[i][j]*direction[j] for j in range(3)) for i in range(3)]
            length = math.sqrt(sum(x*x for x in vector))
            if length < 1e-12:
                raise ValueError("Degenerate target geometry.")
            direction = [x/length for x in vector]
        projections = [sum((p[i]-center[i])*direction[i] for i in range(3)) for p in mesh.positions]
        landmarks.append(Landmark(id=region["joint"], name=region["name"], parent=region["parent"],
            head=[center[i]+min(projections)*direction[i] for i in range(3)],
            tail=[center[i]+max(projections)*direction[i] for i in range(3)]))
    return landmarks


def execute(document, spec):
    target = CharacterDocument.model_validate(document)
    spec = MethodSpec.model_validate(spec)
    if spec.reconstruct and not target.joints:
        target = apply(target, Recipe(operation="construct_rig", landmarks=estimate_landmarks(target), max_influences=spec.max_influences))
    if not target.skins:
        raise ValueError("Method requires observed skin or supported reconstruction inputs.")
    target = apply(target, Recipe(operation="normalize_weights"))
    if spec.binding == "segmented":
        regions = {r["mesh"]: r for r in target.metadata.get("practice_descriptor", {}).get("regions", [])}
        if not target.metadata.get("synthetic") or not regions:
            raise ValueError("Segmented method requires explicit synthetic region labels; real anatomy is not guessed.")
        for skin in target.skins:
            region = regions[skin.mesh_id]
            skin.joints = [region["joint"]] + ([region["parent"]] if region["parent"] else [])
    if spec.binding != "preserve":
        target = apply(target, Recipe(operation="spatial_bind", distance_power=spec.distance_power, max_influences=spec.max_influences))
    if spec.smoothing:
        target = apply(target, Recipe(operation="smooth_weights", strength=spec.smoothing, iterations=spec.smoothing_iterations, max_influences=spec.max_influences))
    return target.model_dump(exclude_none=True)
