from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.autonomy.knowledge import KnowledgeStore
from app.expertise.analysis import ANALYZER_VERSION, analyze, compare, extract_knowledge
from app.expertise.parsers import PARSER_VERSION, parse_asset
from app.expertise.schema import Source
from app.expertise.store import ExpertiseStore, encode, now
from app.memory.long_term import contains_sensitive_value, safe_memory_text
from app.expertise.workshop.repository import WorkshopRepository
from app.expertise.workshop.service import CharacterWorkshop
from app.expertise.training.recipes import RecipeMemory
from app.expertise.training.repository import TrainingRepository
from app.expertise.training.service import SelfTrainingEngine
from app.expertise.training.host import TrainingCoordinator
from app.expertise.production.service import ProductionEngine


class CharacterExpertiseService:
    def __init__(self, store: ExpertiseStore, knowledge: KnowledgeStore) -> None:
        self.store, self.knowledge = store, knowledge
        self.sources_dir = store.path.parent / "character_sources"
        self.sources_dir.mkdir(parents=True, exist_ok=True)
        self.workshop = CharacterWorkshop(WorkshopRepository(store), store, contains_sensitive_value)
        self.recipes = RecipeMemory(store)
        self.training = SelfTrainingEngine(TrainingRepository(store), self.recipes)
        self.training_host = TrainingCoordinator(self.training)
        self.production = ProductionEngine(self)

    def attach_skill_library(self, library):
        """Host mapping to existing generic candidates; no automatic skill activation."""
        def publish(champion):
            task_id = "training-skill:"+champion["id"]
            if any(s.get("source_task_id") == task_id for s in library.list(300)):
                return
            method = champion["method"]
            library.add_candidate({"id": task_id, "title": "Synthetic character workflow: "+champion["context"],
                "goal": "Measured synthetic rig/skinning practice only; adapt and independently verify real assets.",
                "entities": {"application": {"kind": "application", "value": "3D expertise domain / optional Blender"}},
                "subgoals": [{"title": step, "channel": "typed_character_domain", "status": "completed",
                    "acceptance": "Independent paired synthetic validation and non-destructive checkpoints."} for step in method["workflow"]],
                "events": [{"kind": "retry", "summary": "Known failures remain in training evidence; never replay source scripts."}],
                "skill_provenance": {"method_version": champion["id"], "method": method["spec"], "synthetic": True,
                    "scope": champion["scope"], "evidence": champion["evidence"]}})
        self.training.lesson_sink = publish
        def publish_production(identifier, evidence):
            if any(s.get("source_task_id") == identifier for s in library.list(300)):
                return
            library.add_candidate({"id": identifier, "title": "Synthetic full-character construction",
                "goal": "Bounded quad-loft humanoid authoring; independently verify DCC and target fidelity.",
                "subgoals": [{"title": title, "channel": "typed_character_domain", "status": "completed",
                    "acceptance": "Computed synthetic integrity/UV/weight gates; not professional certification."}
                    for title in ("Construct", "Evaluate defects", "Correct", "Compare immutable states", "Keep best")],
                "skill_provenance": {"synthetic": True, "professional_validated": False, "evidence": evidence}})
        self.production.lesson_sink = publish_production

    def propose_learned_method(self, asset_id, version_id):
        from app.expertise.workshop.contracts import Recipe, WorkshopRequest
        champion = self.training.repository.method_version(version_id)
        spec = champion["method"]["spec"]
        target = self.store.asset(asset_id)
        if not target["normalized"].get("skins"):
            raise ValueError("A new real rig still needs explicit anatomical landmarks/application reconstruction support.")
        proposals = [Recipe(operation="normalize_weights")]
        adaptation = "exact weights-only workflow parameters"
        if spec["binding"] != "preserve":
            proposals.append(Recipe(operation="spatial_bind", distance_power=spec["distance_power"], max_influences=spec["max_influences"]))
            if spec["binding"] == "segmented":
                # Never assume synthetic region labels exist on a professional target.
                adaptation = "spatial proposal adapted from synthetic segmented method; region restriction not transferred"
        if spec["smoothing"]:
            proposals.append(Recipe(operation="smooth_weights", strength=spec["smoothing"], iterations=spec["smoothing_iterations"], max_influences=spec["max_influences"]))
        job = self.workshop.create(WorkshopRequest(asset_id=asset_id,
            objective="Test learned parameters as a non-destructive proposal. Independent numeric/application gates remain mandatory.", proposals=proposals))
        return {"workshop": job, "source_method_version": version_id, "adaptation": adaptation,
                "status": "proposal_only_not_applied", "professional_transfer_validated": False}

    def ingest(self, filename: str, content: bytes, source: Source) -> Dict[str, Any]:
        digest = hashlib.sha256(content).hexdigest()
        pipeline = f"{PARSER_VERSION}/{ANALYZER_VERSION}"
        source_value = source.model_dump()
        if contains_sensitive_value(encode(source_value)):
            raise ValueError("Credential-like provenance cannot enter expert memory.")
        identity = hashlib.sha256((digest + pipeline + Path(filename).suffix.casefold() + encode(source_value)).encode()).hexdigest()[:32]
        identifier = "character-" + identity
        try:
            cached = self.store.asset(identifier)
            self.recipes.extract(cached)
            return {**cached, "cache_hit": True}
        except KeyError:
            pass
        document, _raw = parse_asset(filename, content)
        if document.metadata.get("synthetic") is True and not source.synthetic:
            raise ValueError("A declared synthetic fixture cannot be ingested as a real asset.")
        analysis = analyze(document)
        # Deterministic hash path, never caller-supplied source reference.
        blob = self.sources_dir / digest
        if not blob.exists():
            temporary = blob.with_suffix(f".{uuid.uuid4().hex}.tmp")
            temporary.write_bytes(content)
            temporary.replace(blob)
        provenance = {**source_value, "asset_id": identifier, "sha256": digest, "method": pipeline, "created_at": now(),
                      "source_name": Path(filename.replace("\\", "/")).name[:240]}
        asset = {"id": identifier, "name": document.name, "digest": digest, "pipeline_version": pipeline,
                 "created_at": now(), "source": provenance, "source_bytes": len(content), "status": "analyzed",
                 "raw_reference": f"source:sha256:{digest}", "normalized": document.model_dump(exclude_none=True), "analysis": analysis}
        knowledge = []
        for index, record in enumerate(extract_knowledge(analysis)):
            knowledge.append({"id": f"{identifier}:knowledge:{index}", **record, "provenance": provenance, "untrusted": True})
        saved = self.store.put_asset(asset, knowledge)
        self.recipes.extract(saved)
        # Expert retrieval is live from SQLite, including later validation status.
        return {**saved, "cache_hit": False, "knowledge_count": len(knowledge)}

    def compare(self, left: str, right: str) -> Dict[str, Any]:
        return compare(self.store.asset(left), self.store.asset(right))

    def retrieve(self, query: str, limit: int = 6) -> List[Dict[str, Any]]:
        results = [{"id": item["id"], "title": item["topic"], "content": item["statement"],
                 "source": item["provenance"]["asset_id"], "kind": item["kind"], "untrusted": True,
                 "metadata": {"category": "character_analysis", "authority": "synthetic" if item["provenance"]["synthetic"] else "direct_asset_observation",
                              "synthetic": item["provenance"]["synthetic"], "confidence": item["confidence"], "validation": item["validation"],
                              "asset_id": item["provenance"]["asset_id"]}}
                for item in self.store.knowledge(query, limit)]
        learned = []
        if any(word in query.casefold() for word in ("skin", "weight", "deformation", "rig", "character")):
            for item in self.training.evidence():
                learned.append({"id": "training-evidence:"+item["context"]+":"+item["method"]["id"],
                    "title": "Measured synthetic production workflow", "content": encode(item), "source": "character_self_training",
                    "kind": "computed_experience_evidence", "untrusted": True, "metadata": {"category": "character_training", "authority": "synthetic",
                    "synthetic": True, "confidence": item["confidence"], "validation": item["validation"], "professional_validated": False}})
            for item in self.workshop.repository.evidence(True):
                learned.append({"id": "workshop-evidence:"+item["operation"]+":"+str(item["synthetic"]), "title": "Character improvement experience",
                    "content": encode(item), "source": "character_workshop_evidence", "kind": "computed_experience_evidence", "untrusted": True,
                    "metadata": {"category": "character_improvement_experience", "authority": "synthetic" if item["synthetic"] else "measured_asset_trials",
                                 "synthetic": item["synthetic"], "confidence": item["confidence"], "validation": item["status"]}})
        return (learned[:2]+results)[:max(1, min(limit, 20))]

    def record_experience(self, task: Dict[str, Any], retrieved: Optional[List[Dict[str, Any]]] = None) -> None:
        nodes = task.get("subgoals", [])
        value = {"id": "experience-" + task["id"], "task_id": task["id"], "schema_version": 1,
                 "goal": task.get("goal"), "context": {"entities": task.get("entities", {}), "artifacts": task.get("artifacts", [])},
                 "retrieved_knowledge": retrieved or task.get("retrieved_knowledge", []),
                 "plans": {"revision": task.get("plan_revision"), "replans": task.get("replans")},
                 "steps": [{key: node.get(key) for key in ("id", "description", "channel", "acceptance", "attempts", "status", "result_summary", "evaluation", "correction", "error", "attempt_history")} for node in nodes],
                 "observations": task.get("events", []), "result": task.get("summary"), "status": task.get("status"),
                 "verified_success": task.get("status") == "completed" and all(node.get("status") in {"completed", "superseded"} for node in nodes) and bool(nodes),
                 "source_type": "task_experience", "untrusted": True, "updated_at": now()}
        def scrub(item):
            if isinstance(item, str): return safe_memory_text(item)
            if isinstance(item, list): return [scrub(child) for child in item]
            if isinstance(item, dict): return {key: scrub(child) for key, child in item.items()}
            return item
        self.store.save_experience(scrub(value))

    def validate(self, identifier: str, evidence_reference: str, method: str, task_id: Optional[str] = None) -> Dict[str, Any]:
        if not evidence_reference.strip() or not method.strip():
            raise ValueError("Validation requires an explicit evidence reference and method.")
        # Manual authenticated attestation; cannot be triggered by retrieved content.
        return self.store.validate_knowledge(identifier, {"evidence_reference": evidence_reference[:2000], "method": method[:300], "related_task_id": task_id,
                                                         "authority": "authenticated_user_attestation"})

    def dataset(self, include_synthetic: bool = False, validated_only: bool = True, limit: int = 200) -> Dict[str, Any]:
        rows = []
        sample_budget = 200000
        for item in self.store.list_assets(limit):
            if item["synthetic"] and not include_synthetic:
                continue
            asset = self.store.asset(item["id"])
            analysis = asset["analysis"]
            approved = self.store.knowledge(limit=200, asset_id=asset["id"], validated_only=True)
            if validated_only and not approved:
                continue
            for joint in analysis["joints"]:
                if joint["anatomy"]["semantic"] == "unknown":
                    continue
                if validated_only:
                    # No automatic name mapping is a validated anatomical training label.
                    continue
                rows.append({"task": "semantic_rig_mapping", "input": {"name": joint["name"], "parent": joint.get("parent")},
                             "target": joint["anatomy"], "label_type": "name_inference", "ground_truth": False,
                             "provenance": asset["source"], "split_group": asset["digest"]})
            for skin in asset["normalized"]["skins"]:
                if skin.get("weights") is not None:
                    if validated_only and not any(item.get("kind") == "computed_metric" and isinstance(item.get("evidence"), dict) and item["evidence"].get("skin_id") == skin["id"] for item in approved):
                        continue
                    mesh = next(mesh for mesh in asset["normalized"]["meshes"] if mesh["id"] == skin["mesh_id"])
                    if mesh.get("positions"):
                        if len(mesh["positions"]) > sample_budget:
                            continue
                        sample_budget -= len(mesh["positions"])
                        rows.append({"task": "skin_weight_reconstruction", "input": {"positions": mesh["positions"], "joints": skin["joints"]},
                                     "target": skin["weights"], "label_type": "source_observation", "ground_truth": True,
                                     "quality_validated": False,
                                     "provenance": asset["source"], "split_group": asset["digest"]})
        return {"schema_version": 1, "records": rows, "record_count": len(rows), "include_synthetic": include_synthetic,
                "validated_only": validated_only, "limitations": ["Source observations do not establish professional quality.", "Semantic labels are heuristic, not ground truth.", "Split by source digest to prevent source leakage."]}
