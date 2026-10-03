from __future__ import annotations

import copy
from typing import Any, Dict

from app.expertise.schema import CharacterDocument, Joint, Skin
from .contracts import Recipe
from .geometry import binding, edges, segment_distance


def normalize(weights: Dict[str, float], maximum: int = 10000) -> Dict[str, float]:
    selected = sorted(((k, v) for k, v in weights.items() if v > 1e-10), key=lambda pair: (-pair[1], pair[0]))[:maximum]
    total = sum(value for _, value in selected)
    return {key: value/total for key, value in selected} if total else {}


def apply(document: CharacterDocument, recipe: Recipe) -> CharacterDocument:
    target = document.model_copy(deep=True)
    if recipe.operation in {"construct_rig", "align_landmarks"}:
        if target.metadata.get("deformation_space") != "shared_bind":
            raise ValueError("Joint construction/alignment requires explicit shared-bind target landmarks.")
        if not recipe.landmarks:
            raise ValueError("Anatomical landmarks are required; anatomy is not invented from another asset.")
        if target.animations or any(j.constraints or j.inverse_bind_matrix or j.matrix or j.translation or j.rotation or j.scale for j in target.joints):
            raise ValueError("Rest-pose edits need an application retarget/bind adapter for existing animation/constraints.")
        existing = {j.id: j for j in target.joints}
        for landmark in recipe.landmarks:
            if recipe.operation == "align_landmarks" and landmark.id not in existing:
                raise ValueError("Alignment references an unknown joint.")
            if recipe.operation == "construct_rig" and landmark.id in existing:
                raise ValueError("Construction cannot overwrite an existing joint.")
            if landmark.id in existing:
                existing[landmark.id].metadata.update(head=landmark.head, tail=landmark.tail, origin="workshop_landmark_proposal")
            else:
                target.joints.append(Joint(id=landmark.id, name=landmark.name, parent=landmark.parent,
                    metadata={"head": landmark.head, "tail": landmark.tail, "origin": "workshop_landmark_proposal"}))
        # Validate hierarchy before binding. Source observations remain immutable in the version store.
        target = CharacterDocument.model_validate(target.model_dump())
        if recipe.operation == "construct_rig":
            meshes = [m for m in target.meshes if recipe.mesh_id is None or m.id == recipe.mesh_id]
            if not meshes or any(m.skin_id for m in meshes):
                raise ValueError("Construction needs an unskinned target mesh.")
            for mesh in meshes:
                identifier = "workshop-skin:" + mesh.id
                mesh.skin_id = identifier
                target.skins.append(Skin(id=identifier, mesh_id=mesh.id, joints=[j.id for j in target.joints], weights=[{} for _ in range(mesh.vertex_count)]))
            return apply(target, Recipe(operation="spatial_bind", mesh_id=recipe.mesh_id, max_influences=recipe.max_influences))
        return target
    skins = [skin for skin in target.skins if (recipe.skin_id is None or skin.id == recipe.skin_id) and (recipe.mesh_id is None or skin.mesh_id == recipe.mesh_id)]
    if not skins:
        raise ValueError("No matching skin.")
    bind = binding(target) if recipe.operation == "spatial_bind" else None
    for skin in skins:
        if skin.weights is None:
            raise ValueError("No observed weights to edit.")
        mesh = next(m for m in target.meshes if m.id == skin.mesh_id)
        if recipe.operation == "normalize_weights":
            skin.weights = [normalize(w) for w in skin.weights]
        elif recipe.operation == "prune_influences":
            skin.weights = [normalize(w, recipe.max_influences) for w in skin.weights]
        elif recipe.operation == "spatial_bind":
            bones, meshes = bind
            joints = {j.id: j for j in target.joints}
            eligible = [key for key in skin.joints if joints[key].metadata.get("deform") is not False]
            if not eligible or len(eligible) > 128 or not set(eligible).issubset(bones) or mesh.id not in meshes or mesh.vertex_count > 20000:
                raise ValueError("CPU spatial binding requires complete rest-space geometry (up to 128 joints/20,000 vertices per mesh). Larger assets need an accelerated binding adapter.")
            generated = []
            for point in meshes[mesh.id]:
                nearest = sorted(((joint, segment_distance(point, bones[joint])) for joint in eligible), key=lambda pair: (pair[1], pair[0]))[:recipe.max_influences]
                # Dimensionless relative distances avoid overflow/unit-dependent weighting.
                minimum = max(1e-8, nearest[0][1])
                generated.append(normalize({joint: (minimum/max(1e-8, distance))**recipe.distance_power for joint, distance in nearest}))
            skin.weights = generated
        elif recipe.operation == "smooth_weights":
            if not mesh.faces:
                raise ValueError("Weight smoothing requires observed surface adjacency.")
            adjacency = [set() for _ in skin.weights]
            for a, b in edges(mesh):
                adjacency[a].add(b)
                adjacency[b].add(a)
            for _ in range(recipe.iterations):
                old = skin.weights
                updated = []
                for i, weights in enumerate(old):
                    neighbors = adjacency[i]
                    combined = {key: (1-recipe.strength)*weight for key, weight in weights.items()}
                    if neighbors:
                        for neighbor in sorted(neighbors):
                            for key, weight in old[neighbor].items():
                                combined[key] = combined.get(key, 0) + recipe.strength*weight/len(neighbors)
                    else:
                        combined = copy.deepcopy(weights)
                    updated.append(normalize(combined, recipe.max_influences))
                skin.weights = updated
    return CharacterDocument.model_validate(target.model_dump())
