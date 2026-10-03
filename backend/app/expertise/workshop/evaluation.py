from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from app.expertise.schema import CharacterDocument
from .contracts import EVALUATOR_VERSION
from .geometry import binding, cross, dot, edges, pose_point, segment_distance, sub


def signature(document: CharacterDocument) -> Dict[str, Any]:
    """Structural guard: a weight experiment cannot silently change the model/animation."""
    return {"meshes": {m.id: m.model_dump(exclude={"skin_id"}) for m in document.meshes},
            "materials": document.materials, "animations": [a.model_dump() for a in document.animations],
            "objects": document.objects}


def descendants(document, identifier):
    children = {}
    for joint in document.joints:
        children.setdefault(joint.parent, []).append(joint.id)
    result, pending = set(), [identifier]
    while pending:
        current = pending.pop()
        result.add(current)
        pending.extend(children.get(current, []))
    return result


def probe_suite(document: CharacterDocument) -> List[Dict[str, Any]]:
    """Fixed train/held-out poses, shared by all candidates (not picked to favor a result)."""
    try:
        bones, _ = binding(document)
    except ValueError:
        return []
    palette = {key for skin in document.skins for weights in (skin.weights or []) for key, value in weights.items() if value > 1e-8}
    selected = sorted(palette & set(bones))[:8]
    return [{"joint": joint, "degrees": degrees, "axial": axial, "split": split}
            for joint in selected for degrees, axial, split in
            ((20, False, "train"), (45, False, "train"), (-30, False, "held_out"), (70, False, "held_out"), (60, True, "held_out"))]


def evaluate(document: CharacterDocument, suite: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    failures, warnings, count, defects, coverage = [], [], 0, 0, {}
    for skin in document.skins:
        if skin.weights is None:
            warnings.append("Skin %s has no observed vertex weights." % skin.id)
            continue
        covered = set()
        for weights in skin.weights:
            count += 1
            if not weights or sum(weights.values()) <= 1e-10 or abs(sum(weights.values()) - 1) > 1e-5:
                defects += 1
            covered.update(key for key, value in weights.items() if value >= .05)
        coverage[skin.id] = sorted(covered)
    if not document.skins:
        warnings.append("No skin exists; construction needs explicit target landmarks.")
    if defects:
        failures.append({"code": "weight_integrity", "vertices": defects})
    result = {"version": EVALUATOR_VERSION, "integrity": {"tested_vertices": count, "defective_vertices": defects,
              "defect_fraction": defects / max(1, count), "joint_coverage": coverage},
              "failures": failures, "warnings": warnings, "deformation": {"available": False},
              "scope": "numeric_skinning_stress_tests_not_professional_or_artistic_certification"}
    try:
        bones, positions = binding(document)
    except ValueError as exc:
        warnings.append(str(exc))
        result["score"] = 10 * defects / max(1, count)
        return result
    suite = suite if suite is not None else probe_suite(document)
    pose_records, seam_values, distances = [], [], []
    sampled_edges, total_edges = 0, 0
    remaining_edges = 4096
    for skin in document.skins:
        mesh = next(m for m in document.meshes if m.id == skin.mesh_id)
        points, weights = positions.get(mesh.id), skin.weights
        if not points or weights is None or not set(skin.joints).issubset(bones):
            warnings.append("Incomplete bind-space/weight evidence for skin " + skin.id)
            continue
        edge_list = edges(mesh)
        total_edges += len(edge_list)
        # Deterministic distributed sample, never random evidence drift between versions.
        allowance = min(1024, remaining_edges)
        stride = max(1, math.ceil(len(edge_list) / max(1, allowance)))
        sample = edge_list[::stride][:allowance]
        remaining_edges -= len(sample)
        sampled_edges += len(sample)
        indices = sorted({index for edge in sample for index in edge})
        if not indices:
            warnings.append("No surface edges to test on " + mesh.id)
            continue
        available = set(indices)
        face_sample = [f for f in (mesh.faces or []) if set(f).issubset(available)][:1024]

        def area(points, face):
            return sum(math.sqrt(dot(normal, normal))*.5 for normal in
                       (cross(sub(points[face[i]], points[face[0]]), sub(points[face[i+1]], points[face[0]])) for i in range(1, len(face)-1)))

        rest_areas = [area(points, face) for face in face_sample]
        extent = max(1e-8, math.dist([min(p[i] for p in points) for i in range(3)], [max(p[i] for p in points) for i in range(3)]))
        for index in indices:
            total = sum(weights[index].values())
            if total:
                distances.append(sum(weight * segment_distance(points[index], bones[key]) for key, weight in weights[index].items()) / total / extent)
        for a, b in sample:
            keys = set(weights[a]) | set(weights[b])
            seam_values.append(sum(abs(weights[a].get(k, 0)-weights[b].get(k, 0)) for k in keys))
        for probe in suite:
            joint = probe["joint"]
            if joint not in bones:
                continue
            inherited = descendants(document, joint)
            posed = {i: pose_point(points[i], weights[i], joint, inherited, bones, math.radians(probe["degrees"]), probe["axial"]) for i in indices}
            strain, collapsed = [], 0
            for a, b in sample:
                before, after = math.dist(points[a], points[b]), math.dist(posed[a], posed[b])
                if before <= 1e-10:
                    continue
                collapsed += int(after < before*.05)
                strain.append(abs(math.log(max(1e-8, after / before))))
            if strain:
                ordered = sorted(strain)
                collapsed_faces, area_distortion = 0, []
                for face, rest_area in zip(face_sample, rest_areas):
                    if rest_area > 1e-12:
                        posed_area = area(posed, face)
                        collapsed_faces += int(posed_area < rest_area*.05)
                        area_distortion.append(abs(math.log(max(1e-8, posed_area/rest_area))))
                pose_records.append({**probe, "skin_id": skin.id, "edges": len(strain), "mean_log_strain": sum(strain)/len(strain),
                                     "p95_log_strain": ordered[min(len(ordered)-1, int(len(ordered)*.95))], "collapsed_edges": collapsed,
                                     "tested_faces": len(area_distortion), "collapsed_faces": collapsed_faces,
                                     "mean_log_area_distortion": sum(area_distortion)/max(1, len(area_distortion))})
    if pose_records:
        train = [p["mean_log_strain"] for p in pose_records if p["split"] == "train"]
        held = [p["mean_log_strain"] for p in pose_records if p["split"] == "held_out"]
        result["deformation"] = {"available": True, "method": "linear_blend_single_joint_inherited_world_axis_probes",
            "sampled_edges": sampled_edges, "total_edges": total_edges, "sampled": sampled_edges < total_edges,
            "poses": pose_records, "train_mean": sum(train)/max(1, len(train)), "held_out_mean": sum(held)/max(1, len(held)),
            "worst_p95": max(p["p95_log_strain"] for p in pose_records), "collapsed_edges": sum(p["collapsed_edges"] for p in pose_records),
            "collapsed_faces": sum(p["collapsed_faces"] for p in pose_records), "area_distortion": sum(p["mean_log_area_distortion"] for p in pose_records)/len(pose_records),
            "bind_distance": sum(distances)/max(1, len(distances)), "weight_variation": sum(seam_values)/max(1, len(seam_values))}
        if any(j.constraints for j in document.joints):
            warnings.append("Application constraints are not simulated by the CPU pose harness.")
    else:
        warnings.append("No usable pose evidence. Weight integrity alone does not establish deformation quality.")
    deformation = result["deformation"]
    result["score"] = 10*defects/max(1, count) + (deformation.get("bind_distance", 0) + .15*deformation.get("weight_variation", 0)
                       + .2*deformation.get("train_mean", 0) + .4*deformation.get("held_out_mean", 0) + .1*deformation.get("area_distortion", 0))
    return result


def judge(before: Dict[str, Any], after: Dict[str, Any], original: CharacterDocument, candidate: CharacterDocument) -> Dict[str, Any]:
    reasons = []
    if signature(original) != signature(candidate):
        reasons.append("Protected geometry/material/animation/object data changed.")
    if not {j.id for j in original.joints}.issubset({j.id for j in candidate.joints}):
        reasons.append("Existing joints were removed.")
    if after["integrity"]["defective_vertices"] > before["integrity"]["defective_vertices"]:
        reasons.append("Weight integrity regressed.")
    for skin, supported in before["integrity"]["joint_coverage"].items():
        if not set(supported).issubset(after["integrity"]["joint_coverage"].get(skin, [])):
            reasons.append("Meaningful joint coverage was lost on " + skin)
    a, b = before["deformation"], after["deformation"]
    if a["available"]:
        if not b["available"] or len(b["poses"]) != len(a["poses"]):
            reasons.append("Pose evidence coverage regressed.")
        else:
            # Per-probe gates prevent improvements in the aggregate from hiding a local failure.
            for old, new in zip(a["poses"], b["poses"]):
                if any(old[key] != new[key] for key in ("joint", "split", "degrees", "axial", "skin_id")):
                    reasons.append("Pose evidence identity changed.")
                    break
                if (new["mean_log_strain"] > max(old["mean_log_strain"]*1.12, old["mean_log_strain"]+.015)
                    or new["collapsed_edges"] > old["collapsed_edges"] or new.get("collapsed_faces", 0) > old.get("collapsed_faces", 0)
                    or new.get("mean_log_area_distortion", 0) > max(old.get("mean_log_area_distortion", 0)*1.15, old.get("mean_log_area_distortion", 0)+.03)):
                    reasons.append("A held-out/train pose regressed: " + old["joint"])
                    break
    improved = after["score"] < before["score"] - 1e-7
    constructed = (not original.skins and bool(candidate.skins) and b["available"] and after["integrity"]["defective_vertices"] == 0
                   and b["collapsed_edges"] == 0 and b["collapsed_faces"] == 0 and b["held_out_mean"] < .4 and b["worst_p95"] < 2)
    if not improved and not constructed:
        reasons.append("No measured improvement.")
    return {"accepted": not reasons, "reasons": reasons, "score_delta": after["score"]-before["score"],
            "scope": "tested_numeric_evidence_only", "construction": constructed}
