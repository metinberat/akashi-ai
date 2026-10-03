"""Recover observed production relations; historical intent/order is not observable."""
import hashlib

from app.expertise.schema import CharacterDocument
from app.expertise.store import encode, now
from .contracts import RECIPE_VERSION


def production_recipe(asset):
    document = CharacterDocument.model_validate(asset["normalized"])
    analysis = asset["analysis"]
    steps, relationships = [], []
    def step(key, title, kind, evidence, validation, depends=()):
        steps.append({"id": key, "title": title, "epistemic_status": kind, "evidence": evidence,
                      "dependencies": list(depends), "validation_criteria": validation, "executable": False})
    step("surface", "Observed geometry/surface organization", "observed_fact",
         [{"mesh": m.id, "vertices": m.vertex_count, "uvs": m.uv_maps, "materials": m.materials,
           "modifiers_in_source_order": m.modifiers, "morph_targets": m.morph_targets} for m in document.meshes],
         ["Preserve topology/UVs/material relationships; validate any production edits."])
    step("rig", "Observed skeleton, rest representation and constraint graph", "observed_fact",
         [{"joint": j.id, "parent": j.parent, "rest_available": bool(j.matrix or j.translation or j.metadata.get("head")),
           "constraints": j.constraints} for j in document.joints], ["Hierarchy references resolve; rest/bind correspondence is explicit."])
    step("binding", "Observed mesh-to-skeleton binding", "observed_fact",
         [{"skin": s.id, "mesh": s.mesh_id, "joints": s.joints, "weights_available": s.weights is not None} for s in document.skins],
         ["Weights normalize; influences/coverage and held-out deformation are tested."], ("surface", "rig"))
    for skin in document.skins:
        relationships.append({"subject": skin.mesh_id, "relation": "bound_to", "objects": skin.joints, "evidence": skin.id, "kind": "observed_fact"})
    for joint in document.joints:
        for constraint in joint.constraints:
            relationships.append({"subject": joint.id, "relation": "constrained_by", "constraint": constraint,
                                  "kind": "observed_fact", "function_validated": False})
    step("surface_network", "Observed material/shader/texture assignments", "observed_fact", document.materials,
         ["Texture references do not imply texture data was available or loaded."])
    step("motion", "Observed animation/facial channels", "observed_fact",
         [{"clip": a.id, "channels": len(a.channels), "targets": sorted({str(c.get("target")) for c in a.channels})} for a in document.animations],
         ["Recreated channels must be inspected in the application; clip presence is not animation readiness."], ("rig", "binding"))
    step("testing", "Possible production deformation validation stage", "hypothesis",
         {"basis": "Rig/skin relations suggest testing before delivery; actual author workflow is unknown."},
         ["Numerical probes, application evidence and domain review; do not infer quality from metadata."], ("binding",))
    roles = analysis["inferred"]["role_counts"]
    patterns = {"roles": roles, "semantic_counts": analysis["inferred"]["semantic_counts"],
                "skin_metrics": analysis["computed"]["skin_metrics"], "hierarchy_depth": analysis["computed"]["hierarchy_depth"],
                "mesh_metrics": analysis["computed"]["mesh_metrics"], "animation_metrics": analysis["computed"]["animation_metrics"]}
    blueprints = [{"id": j["id"], "name": j["name"], "parent": j.get("parent"), "anatomy": j["anatomy"]} for j in analysis["joints"]]
    pattern_key = hashlib.sha256(encode({"semantics": patterns["semantic_counts"], "roles": roles,
        "influence_limits": sorted(m.get("max_influences", 0) for m in patterns["skin_metrics"])}).encode()).hexdigest()
    # This fingerprint ignores renamed/provenance-only exports but retains geometry/rest evidence.
    structural = {"joints": [{"parent_index": next((i for i, p in enumerate(document.joints) if p.id == j.parent), None),
                    "matrix": j.matrix, "head": j.metadata.get("head"), "tail": j.metadata.get("tail")} for j in document.joints],
                  "meshes": [{"positions": m.positions, "faces": m.faces, "vertices": m.vertex_count} for m in document.meshes]}
    return {"id": "recipe-"+hashlib.sha256((asset["id"]+RECIPE_VERSION).encode()).hexdigest()[:32],
            "version": RECIPE_VERSION, "asset_id": asset["id"], "provenance": asset["source"], "created_at": now(),
            "source_group": hashlib.sha256(encode(structural).encode()).hexdigest(), "pattern_key": pattern_key,
            "steps": steps, "relationships": relationships, "patterns": patterns, "rig_blueprint": blueprints,
            "historical_workflow": "unknown", "dependency_order": "inferred_prerequisites_not_observed_author_history",
            "validation": "source_observations_and_computed_metrics_only", "untrusted": True,
            "practice_readiness": {"weights": bool(document.skins) and all(s.weights is not None for s in document.skins),
                                   "joint_reconstruction": "labelled_synthetic_geometry_only", "facial_production": "not_implemented",
                                   "ik_fk_recreation": "observations_only_not_functionally_recreated", "shader_recreation": "observations_only"},
            "limitations": document.unavailable + ["Bone-name anatomy/role mapping is inference.", "A production recipe is not executable source code or validated universal expertise."]}


class RecipeMemory:
    def __init__(self, store):
        self.store = store
        with store.connection() as db:
            db.executescript("CREATE TABLE IF NOT EXISTS production_recipes(id TEXT PRIMARY KEY,asset_id TEXT NOT NULL REFERENCES assets(id),body TEXT NOT NULL); CREATE INDEX IF NOT EXISTS production_recipe_asset ON production_recipes(asset_id);")

    def extract(self, asset):
        recipe = production_recipe(asset)
        with self.store.connection() as db:
            db.execute("INSERT OR IGNORE INTO production_recipes VALUES(?,?,?)", (recipe["id"], asset["id"], encode(recipe)))
        return recipe

    def list(self, limit=100):
        import json
        with self.store.connection() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT body FROM production_recipes ORDER BY rowid DESC LIMIT ?", (max(1, min(500, limit)),))]

    def for_asset(self, identifier):
        return self.extract(self.store.asset(identifier))

    def compare_patterns(self):
        groups = {}
        for recipe in self.list(500):
            key = (recipe["pattern_key"], recipe["provenance"]["synthetic"])
            group = groups.setdefault(key, {"pattern_key": key[0], "synthetic": key[1], "sources": set(), "recipes": [], "patterns": recipe["patterns"]})
            group["sources"].add(recipe["source_group"])
            group["recipes"].append(recipe["id"])
        return [{**{k: v for k, v in g.items() if k != "sources"}, "independent_source_groups": len(g["sources"]),
                 "confidence": len(g["sources"])/(len(g["sources"])+4), "validation": "recurring_observation_not_causal_or_quality_validation"} for g in groups.values()]
