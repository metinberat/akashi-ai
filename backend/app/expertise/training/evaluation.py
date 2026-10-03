"""Independent analytic synthetic reference; not professional/artistic validation."""
import math

from app.expertise.schema import CharacterDocument
from app.expertise.workshop.geometry import binding, pose_point
from app.expertise.workshop.repository import digest

EVALUATOR_VERSION = "synthetic-reference-pose-1.0"


def protected(document):
    document = CharacterDocument.model_validate(document).model_dump(exclude_none=True)
    return digest({key: document.get(key, []) for key in ("meshes", "materials", "animations", "objects")
                   if key != "meshes"} | {"meshes": [{k: v for k, v in m.items() if k != "skin_id"} for m in document["meshes"]]})


def evaluate(candidate, reference, initial):
    c, r = CharacterDocument.model_validate(candidate), CharacterDocument.model_validate(reference)
    cb, cp = binding(c)
    rb, rp = binding(r)
    extent = max(1e-8, math.dist([min(p[k] for points in rp.values() for p in points) for k in range(3)],
                               [max(p[k] for points in rp.values() for p in points) for k in range(3)]))
    cs, rs = {s.mesh_id: s for s in c.skins}, {s.mesh_id: s for s in r.skins}
    missing = len(set(rb)-set(cb))/max(1, len(rb))
    joint_error = sum((math.dist(cb[j][0], rb[j][0])+math.dist(cb[j][1], rb[j][1]))/(2*extent) if j in cb else 1. for j in rb)/max(1, len(rb))
    weight_errors, normalization, pose_errors = [], [], []
    parents = {j.id: j.parent for j in r.joints}
    actual_parents = {j.id: j.parent for j in c.joints}
    hierarchy_error = sum(actual_parents.get(j) != parent or j not in actual_parents for j, parent in parents.items())/max(1, len(parents))
    # Every referenced region is tested, with bounded samples; held-out angles never enter method execution.
    for mesh_id, skin in rs.items():
        candidate_skin = cs.get(mesh_id)
        if not candidate_skin or candidate_skin.weights is None:
            weight_errors.append(1.)
            pose_errors.append(1.)
            continue
        for actual, truth in zip(candidate_skin.weights, skin.weights):
            weight_errors.append(sum(abs(actual.get(j, 0)-truth.get(j, 0)) for j in set(actual)|set(truth))/2)
            normalization.append(abs(sum(actual.values())-1))
        probe = skin.joints[0]
        descendants = {probe}
        actual_descendants = {probe}
        for _ in range(len(parents)):
            descendants.update(j for j, p in parents.items() if p in descendants)
        for _ in range(len(actual_parents)):
            actual_descendants.update(j for j, p in actual_parents.items() if p in actual_descendants)
        if probe not in cb:
            pose_errors.append(1.)
            continue
        stride = max(1, len(rp[mesh_id])//32)
        for index in range(0, len(rp[mesh_id]), stride):
            for angle, axial in ((-.61, False), (1.13, False), (.89, True)):
                truth = pose_point(rp[mesh_id][index], skin.weights[index], probe, descendants, rb, angle, axial)
                actual = pose_point(cp[mesh_id][index], candidate_skin.weights[index], probe, actual_descendants, cb, angle, axial)
                pose_errors.append(math.dist(truth, actual)/extent)
    weight = sum(weight_errors)/max(1, len(weight_errors))
    pose = sum(pose_errors)/max(1, len(pose_errors))
    intact = protected(candidate) == protected(initial)
    normalized = max(normalization, default=1.) < 1e-6
    loss = .5*weight + .3*pose + .2*joint_error + missing + hierarchy_error
    return {"version": EVALUATOR_VERSION, "loss": loss, "weight_l1": weight, "pose_rm_distance": pose,
            "joint_error": joint_error, "hierarchy_error": hierarchy_error, "missing_joint_fraction": missing, "normalization_max_error": max(normalization, default=1.),
            "protected_data_intact": intact, "passed": intact and normalized and not missing and not hierarchy_error and loss < .045,
            "pose_samples": len(pose_errors), "synthetic": True,
            "scope": "analytic synthetic reference under isolated linear-blend-skinning poses; not artistic or production-rig quality"}
