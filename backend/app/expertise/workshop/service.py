from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable, Dict, Optional, Protocol

from app.expertise.schema import CharacterDocument
from app.expertise.store import now
from .contracts import EVALUATOR_VERSION, POLICY_VERSION, Recipe, WorkshopRequest
from .evaluation import evaluate, judge, probe_suite
from .operations import apply
from .repository import WorkshopRepository, digest


class ExpertisePort(Protocol):
    def asset(self, identifier: str) -> Dict[str, Any]: ...
    def knowledge(self, query: str = "", limit: int = 20, **kwargs): ...
    def save_experience(self, value: Dict[str, Any]) -> None: ...


class CharacterWorkshop:
    """Knowledge -> typed proposals -> measured variants -> conservative best selection.

    No model text, source instructions, application scripts or shell commands are
    executed here. A host can mount this domain independently of AKASHI Core.
    """
    def __init__(self, repository: WorkshopRepository, expertise: ExpertisePort, objective_guard: Optional[Callable[[str], bool]] = None):
        self.repository, self.expertise = repository, expertise
        self.objective_guard = objective_guard
        self.stopping = threading.Event()

    def create(self, request: WorkshopRequest):
        asset = self.expertise.asset(request.asset_id)
        document = CharacterDocument.model_validate(asset["normalized"])
        if self.objective_guard and self.objective_guard(request.objective):
            raise ValueError("Credential-like objectives cannot enter experience storage.")
        records = self.expertise.knowledge("skin weights influences deformation twist", 100)
        # Synthetic observations never become real-asset guidance. Numeric records only;
        # a retrieved paragraph cannot choose arbitrary code or authorize a modification.
        records = [r for r in records if r["provenance"]["synthetic"] == asset["source"]["synthetic"]]
        influences = []
        for record in records:
            evidence = record.get("evidence")
            if record["kind"] == "computed_metric" and record["validation"] == "validated" and isinstance(evidence, dict):
                count = evidence.get("max_influences")
                if isinstance(count, int) and 1 <= count <= 8:
                    influences.append(count)
        maximum = sorted(influences)[len(influences)//2] if influences else 4
        experience_evidence = [e for e in self.repository.evidence(True) if e["synthetic"] == asset["source"]["synthetic"]]
        supported = {e["operation"] for e in experience_evidence if e["independent_positive_sources"] >= 3 and not e["independent_negative_sources"]}
        proposals = [p.model_dump() for p in request.proposals]
        defaults = [Recipe(operation=operation, max_influences=maximum, strength=strength).model_dump()
                         for operation, strength in (("normalize_weights", .2), ("prune_influences", .2), ("spatial_bind", .2),
                                                     ("smooth_weights", .1), ("smooth_weights", .25), ("smooth_weights", .5))]
        defaults.sort(key=lambda p: (p["operation"] != "normalize_weights", p["operation"] not in supported))
        proposals.extend(defaults)
        suite = probe_suite(document)
        # Renaming/re-exporting a source must not manufacture independent evidence.
        # Ignore display/provenance labels, retain actual bind/geometry/weight data.
        joint_ids = {joint.id: index for index, joint in enumerate(document.joints)}
        evidence_group = digest({"joints": [{"parent": joint_ids.get(j.parent), "translation": j.translation, "rotation": j.rotation,
            "matrix": j.matrix, "inverse_bind_matrix": j.inverse_bind_matrix, "head": j.metadata.get("head"), "tail": j.metadata.get("tail"),
            "deform": j.metadata.get("deform"), "constraints": j.constraints} for j in document.joints],
            "meshes": [{"positions": m.positions, "faces": m.faces, "vertices": m.vertex_count} for m in document.meshes],
            "skins": [{"joints": [joint_ids[k] for k in s.joints], "weights": [{str(joint_ids[k]): v for k, v in w.items()} for w in (s.weights or [])]} for s in document.skins]})
        job = {"id": "improvement-"+uuid.uuid4().hex, "asset_id": asset["id"], "source_digest": asset["digest"],
            "evidence_group": evidence_group,
            "synthetic": asset["source"]["synthetic"], "objective": request.objective, "policy": POLICY_VERSION,
            "max_attempts": request.max_attempts, "proposals": proposals, "next_proposal": 0, "pose_suite": suite,
            "evaluator_version": EVALUATOR_VERSION,
            "retrieved_knowledge": [{"id": r["id"], "kind": r["kind"], "validation": r["validation"], "source": r["provenance"]["asset_id"]} for r in records],
            "retrieved_experience": experience_evidence,
            "decision_basis": {"max_influences": maximum, "method": "validated_numeric_prior_median" if influences else "bounded_default_not_professional_truth",
                               "limitations": "Prior structures are guidance, never copied anatomy or certified quality."}}
        return self.repository.create(job, document.model_dump(exclude_none=True), evaluate(document, suite))

    def run(self, identifier: str, steps: int = 16):
        job, token = self.repository.claim(identifier)
        if token is None:
            return job
        if job.get("evaluator_version") != EVALUATOR_VERSION:
            self.repository.checkpoint(identifier, token, {"status": "paused_recovery", "pause_reason": "Evaluator changed. Create a new run; historical evidence is immutable."})
            raise ValueError("Evaluator changed; recreate the improvement from the preserved source.")
        started, iterations = time.monotonic(), 0
        try:
            while job["attempts"] < job["max_attempts"] and job["next_proposal"] < len(job["proposals"]):
                job = self.repository.get(identifier)
                if job["cancel_requested"]:
                    job = self.repository.checkpoint(identifier, token, {"status": "cancelled"})
                    break
                if self.stopping.is_set() or iterations >= max(1, min(16, steps)) or time.monotonic()-started > 90:
                    job = self.repository.checkpoint(identifier, token, {"status": "paused", "pause_reason": "Bounded worker budget/shutdown; best checkpoint preserved."})
                    break
                best = self.repository.version(job["best_version"])
                original = CharacterDocument.model_validate(best["document"])
                recipe = Recipe.model_validate(job["proposals"][job["next_proposal"]])
                candidate, report = original, best["evaluation"]
                try:
                    candidate = apply(original, recipe)
                    suite = job["pose_suite"] or probe_suite(candidate)
                    report = evaluate(candidate, suite)
                    decision = judge(best["evaluation"], report, original, candidate)
                    if self.repository.rejected_in_application(job["source_digest"], digest(candidate.model_dump(exclude_none=True))):
                        decision.update(accepted=False, reasons=["This exact candidate already failed actual application verification. Use another strategy."])
                except ValueError as exc:
                    # Preconditions failing are real failed attempts, not fabricated successes.
                    decision = {"accepted": False, "reasons": [str(exc)], "category": "unsupported_or_missing_evidence", "score_delta": 0}
                version = {"id": "version-"+uuid.uuid4().hex, "job_id": identifier, "parent": best["id"], "created_at": now(),
                    "digest": digest(candidate.model_dump(exclude_none=True)), "recipe": recipe.model_dump(), "evaluation": report,
                    "decision": decision, "synthetic": job["synthetic"], "source_digest": job["source_digest"],
                    "rationale": "Repair measured defects, test on fixed train/held-out poses, retain only non-regressing evidence."}
                changes = {"next_proposal": job["next_proposal"]+1}
                if decision["accepted"] and not job["pose_suite"]:
                    changes["pose_suite"] = probe_suite(candidate)
                # Each next trial starts from best, not from a degraded candidate. Changing
                # smoothing strength after rejection is a bounded alternative strategy.
                job = self.repository.checkpoint(identifier, token, changes, version, candidate.model_dump(exclude_none=True))
                iterations += 1
                self._experience(job)
            else:
                cancelled = self.repository.get(identifier)["cancel_requested"]
                job = self.repository.checkpoint(identifier, token, {"status": "cancelled" if cancelled else "completed", "result": "Bounded improvement search completed; inspect quality scope and rejected attempts."})
        except Exception:
            self.repository.checkpoint(identifier, token, {"status": "paused_recovery", "pause_reason": "Worker failed; immutable best checkpoint retained."})
            raise
        self._experience(job)
        return job

    def _experience(self, job):
        versions = self.repository.versions(job["id"])
        self.expertise.save_experience({"id": "experience-"+job["id"], "task_id": job["id"], "schema_version": 2,
            "source_type": "character_improvement_experience", "synthetic": job["synthetic"], "source_digest": job["source_digest"],
            "evidence_group": job.get("evidence_group", job["source_digest"]),
            "goal": job["objective"], "context": {"asset_id": job["asset_id"], "best_version": job["best_version"]},
            "retrieved_knowledge": job["retrieved_knowledge"], "decision_basis": job["decision_basis"],
            "retrieved_experience": job.get("retrieved_experience", []),
            "steps": [{"version": v["id"], "parent": v["parent"], "action": v["recipe"], "observation": v["evaluation"],
                       "evaluation": v["decision"], "application_evidence": v.get("application_evidence", []), "rationale": v.get("rationale"), "correction": "Retry from best with next bounded proposal."} for v in versions],
            "status": job["status"], "verified_success": job["best_version"] != job["baseline_version"],
            "validation_scope": "numeric_tests_only", "untrusted": True, "updated_at": now()})

    def shutdown(self):
        self.stopping.set()

    def weight_patch(self, identifier):
        job = self.repository.get(identifier)
        source = self.repository.version(job["baseline_version"])["document"]
        version = self.repository.version(job["best_version"])
        document = CharacterDocument.model_validate(version["document"])
        # This adapter materializes weights only. New/rest-edited bones require a
        # different fixed application adapter, not a hidden partial application.
        if source["joints"] != document.model_dump(exclude_none=True)["joints"]:
            raise ValueError("Rig changes cannot be exported through the weight-only Blender adapter.")
        meshes, palette = {m.id: m for m in document.meshes}, {j.id: j for j in document.joints}
        patches = []
        for skin in document.skins:
            mesh = meshes[skin.mesh_id]
            if skin.weights is None or mesh.positions is None or mesh.faces is None:
                raise ValueError("Weight patches need complete observed geometry and weights.")
            names = {key: palette[key].name for key in skin.joints}
            if len(set(names.values())) != len(names):
                raise ValueError("Ambiguous bone names in application patch.")
            patches.append({"mesh": mesh.id, "geometry_digest": digest({"positions": mesh.positions, "faces": mesh.faces}),
                            "bones": names, "weights": skin.weights})
        return {"schema_version": 1, "version_id": version["id"], "synthetic": job["synthetic"], "patches": patches,
                "quality_scope": version["evaluation"]["scope"], "source_digest": job["source_digest"]}

    def dataset(self, include_synthetic=False):
        rows = []
        for job in self.repository.list(100):
            if job["synthetic"] and not include_synthetic:
                continue
            versions = self.repository.versions(job["id"])
            for version in versions:
                if not version["recipe"]:
                    continue
                application_evidence = version.get("application_evidence", [])
                actual_evidence = [e for e in application_evidence if str(e.get("scope", "")).startswith("actual_application")]
                application_rejected = any(not e["accepted"] for e in actual_evidence)
                rows.append({"task": "character_improvement_evaluation", "input": {"parent_version": version["parent"], "recipe": version["recipe"]},
                    "target": {"accepted": version["decision"]["accepted"] and not application_rejected,
                               "numeric_accepted": version["decision"]["accepted"],
                               "application_validation": "failed" if application_rejected else "passed" if actual_evidence else "unverified",
                               "score_delta": version["decision"]["score_delta"], "reasons": version["decision"]["reasons"]},
                    "application_evidence": application_evidence,
                    "evaluation_version": version["evaluation"]["version"], "synthetic": job["synthetic"], "split_group": job.get("evidence_group", job["source_digest"]), "source_digest": job["source_digest"],
                    "ground_truth": False, "label_type": "measured_policy_preference_not_artistic_quality", "best_version": job["best_version"]})
        return {"records": rows, "record_count": len(rows), "scope": "offline_evaluation_or_preference_dataset", "include_synthetic": include_synthetic}
