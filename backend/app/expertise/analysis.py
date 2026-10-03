"""Deterministic structural analysis. Names suggest semantics, never prove anatomy."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List

from app.expertise.schema import CharacterDocument

ANALYZER_VERSION = "character-1.1"


def semantic_joint(name: str) -> Dict[str, Any]:
    value = re.sub(r"([a-z])([A-Z])", r"\1_\2", name).casefold()
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
    parts = value.split("_")
    side = "left" if "left" in parts or "l" in parts else "right" if "right" in parts or "r" in parts else "center"
    value = "_".join(part for part in parts if part not in {"left", "right", "l", "r", "mixamorig", "bone", "def"})
    patterns = [
        ("thumb", "thumb", "hand"), ("index", "index_finger", "hand"), ("middle", "middle_finger", "hand"),
        ("ring", "ring_finger", "hand"), ("pinky|little", "little_finger", "hand"),
        ("forearm|lower_arm|lowerarm", "forearm", "arm"), ("upper_arm|upperarm|^arm", "upper_arm", "arm"),
        ("clavicle|shoulder", "clavicle", "shoulder"), ("hand|wrist", "wrist", "hand"),
        ("thigh|upper_leg|upleg", "thigh", "leg"), ("shin|calf|lower_leg|^leg", "shin", "leg"),
        ("toe", "toe", "foot"), ("foot|ankle", "ankle", "foot"), ("spine|chest", "spine", "torso"),
        ("hips|pelvis", "pelvis", "torso"), ("neck", "neck", "neck"), ("head", "head", "head"),
        ("jaw|eye|brow|lip|cheek|tongue", "facial", "face"), ("root", "root", "root"),
    ]
    semantic, region = "unknown", "unknown"
    for pattern, candidate, area in patterns:
        if re.search(pattern, value):
            semantic, region = candidate, area
            break
    flags = [key for key in ("twist", "helper", "ik", "fk", "control") if re.search(rf"(^|_){key}(_|\d|$)", value)]
    return {"semantic": semantic, "region": region, "side": side, "roles": flags,
            "basis": "inferred_from_name", "confidence": 0.8 if semantic != "unknown" else 0.0}


def analyze(document: CharacterDocument) -> Dict[str, Any]:
    parents = {joint.id: joint.parent for joint in document.joints}
    normalized = [{**joint.model_dump(exclude_none=True), "anatomy": semantic_joint(joint.name)} for joint in document.joints]
    depths = {}
    for joint in document.joints:
        cursor, chain = joint.id, []
        while cursor is not None and cursor not in depths:
            chain.append(cursor)
            cursor = parents.get(cursor)
        depth = depths.get(cursor, 0)
        for identifier in reversed(chain):
            depth += 1
            depths[identifier] = depth
    mapping = Counter(joint["anatomy"]["semantic"] for joint in normalized)
    sides = Counter(joint["anatomy"]["side"] for joint in normalized)
    roles = Counter(role for joint in normalized for role in joint["anatomy"]["roles"])
    chains = {}
    for joint in normalized:
        anatomy = joint["anatomy"]
        group = anatomy["side"] + ":" + (anatomy["semantic"] if "finger" in anatomy["semantic"] or anatomy["semantic"] == "thumb" else anatomy["region"])
        chains.setdefault(group, []).append(joint["id"])
    chains = {key: sorted(ids, key=lambda identifier: depths[identifier]) for key, ids in chains.items() if len(ids) > 1}
    symmetry = []
    for semantic in sorted(mapping):
        left = [joint for joint in normalized if joint["anatomy"]["semantic"] == semantic and joint["anatomy"]["side"] == "left"]
        right = [joint for joint in normalized if joint["anatomy"]["semantic"] == semantic and joint["anatomy"]["side"] == "right"]
        if left or right:
            symmetry.append({"semantic": semantic, "left_count": len(left), "right_count": len(right), "count_difference": len(left) - len(right)})
    skin_metrics = []
    for skin in document.skins:
        weights = skin.weights
        metrics: Dict[str, Any] = {"skin_id": skin.id, "mesh_id": skin.mesh_id, "joint_count": len(skin.joints), "weights_available": weights is not None}
        if weights is not None:
            counts = [sum(weight > 1e-8 for weight in row.values()) for row in weights]
            used = {joint for row in weights for joint, weight in row.items() if weight > 1e-8}
            metrics.update({"vertex_count": len(weights), "mean_influences": sum(counts) / max(1, len(counts)),
                            "max_influences": max(counts, default=0), "unweighted_vertices": counts.count(0),
                            "unnormalized_vertices": sum(abs(sum(row.values()) - 1) > 0.001 for row in weights),
                            "joint_coverage": len(used) / max(1, len(skin.joints)),
                            "weight_sparsity": 1 - sum(counts) / max(1, len(weights) * len(skin.joints)),
                            "influence_histogram": dict(Counter(counts))})
        skin_metrics.append(metrics)
    meshes = []
    for mesh in document.meshes:
        metrics = {"mesh_id": mesh.id, "vertex_count": mesh.vertex_count, "face_count": mesh.face_count,
                   "uv_count": len(mesh.uv_maps), "material_slots": len(mesh.materials), "morph_target_count": len(mesh.morph_targets)}
        if mesh.faces is not None:
            edge_use: Counter = Counter()
            parent = list(range(mesh.vertex_count))
            def find(index: int) -> int:
                while parent[index] != index:
                    parent[index] = parent[parent[index]]
                    index = parent[index]
                return index
            for face in mesh.faces:
                for start, end in zip(face, face[1:] + face[:1]):
                    edge_use[tuple(sorted((start, end)))] += 1
                    parent[find(start)] = find(end)
            metrics.update({"edge_count": len(edge_use), "boundary_edges": sum(count == 1 for count in edge_use.values()),
                            "nonmanifold_edges": sum(count > 2 for count in edge_use.values()),
                            "connected_components": len({find(index) for index in range(mesh.vertex_count)}),
                            "face_sizes": dict(Counter(len(face) for face in mesh.faces))})
        meshes.append(metrics)
    animations = []
    for clip in document.animations:
        count = sum(int(channel.get("keyframe_count", len(channel.get("times", [])))) for channel in clip.channels)
        animations.append({"clip_id": clip.id, "duration": clip.duration, "frame_rate": clip.frame_rate,
                           "channel_count": len(clip.channels), "keyframe_count": count,
                           "keyframes_per_second": count / clip.duration if clip.duration else None,
                           "animated_targets": sorted({str(channel.get("target")) for channel in clip.channels}),
                           "root_motion": "not_evaluated", "looping": "not_evaluated"})
    return {"analyzer_version": ANALYZER_VERSION, "joints": normalized,
            "observed": {"has_rig": bool(document.joints), "has_skin": bool(document.skins), "has_animation": bool(document.animations),
                         "morph_targets": sum(len(mesh.morph_targets) for mesh in document.meshes),
                         "joint_count": len(document.joints), "mesh_count": len(document.meshes), "material_count": len(document.materials)},
            "computed": {"hierarchy_depth": max(depths.values(), default=0), "depth_by_joint": depths,
                         "skin_metrics": skin_metrics, "mesh_metrics": meshes, "animation_metrics": animations},
            "inferred": {"semantic_counts": dict(mapping), "side_counts": dict(sides), "role_counts": dict(roles),
                         "anatomical_chain_groups": chains,
                         "symmetry_by_semantic_count": symmetry, "facial_named_joints": mapping.get("facial", 0)},
            "unavailable": document.unavailable}


def extract_knowledge(analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    records = []
    def add(kind: str, topic: str, statement: str, evidence: Any, confidence: float = 1.0) -> None:
        records.append({"kind": kind, "topic": topic, "statement": statement, "evidence": evidence,
                        "confidence": confidence, "validation": "unvalidated" if kind in {"inferred_principle", "hypothesis"} else "measured"})
    observed = analysis["observed"]
    add("observed_fact", "skeleton structure", f"Source contains {observed['joint_count']} joints and {observed['mesh_count']} meshes.", observed)
    add("computed_metric", "rig hierarchy", f"Maximum skeleton depth: {analysis['computed']['hierarchy_depth']}.", analysis["computed"]["hierarchy_depth"])
    for metric in analysis["computed"]["skin_metrics"]:
        if metric["weights_available"]:
            add("computed_metric", "skin weights influence distribution", f"Skin {metric['skin_id']}: mean {metric['mean_influences']:.3f} influences per vertex; {metric['unweighted_vertices']} unweighted vertices.", metric)
    twist = [joint for joint in analysis["joints"] if "twist" in joint["anatomy"]["roles"]]
    if twist:
        add("observed_fact", "twist bone naming", f"{len(twist)} source joint names contain a twist role marker.", [joint["id"] for joint in twist])
        add("hypothesis", "forearm twist deformation", "Twist-named joints may distribute axial rotation. Deformation testing is required; names alone do not establish function or quality.", [joint["id"] for joint in twist], 0.55)
    if not observed["has_animation"]:
        add("observed_fact", "animation availability", "No animation clips were present in the parsed source.", {"clip_count": 0})
    return records


def compare(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    a, b = left["analysis"], right["analysis"]
    sa, sb = set(a["inferred"]["semantic_counts"]) - {"unknown"}, set(b["inferred"]["semantic_counts"]) - {"unknown"}
    return {"left": left["id"], "right": right["id"], "basis": "semantic mapping; independent of topology",
            "shared_semantics": sorted(sa & sb), "left_only_semantics": sorted(sa - sb), "right_only_semantics": sorted(sb - sa),
            "semantic_jaccard": len(sa & sb) / max(1, len(sa | sb)),
            "joint_count_delta": b["observed"]["joint_count"] - a["observed"]["joint_count"],
            "hierarchy_depth_delta": b["computed"]["hierarchy_depth"] - a["computed"]["hierarchy_depth"],
            "skin_metrics": {"left": a["computed"]["skin_metrics"], "right": b["computed"]["skin_metrics"]},
            "limitations": ["Name-derived mappings are inferred.", "No deformation-quality ranking is implied."]}
