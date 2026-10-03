"""Bounded, resumable practice controller independent of AKASHI clients/providers."""
import math
import random
import threading
import time
import uuid

from app.expertise.store import now
from app.expertise.workshop.repository import digest
from .contracts import TrainingRequest, TRAINER_VERSION, GENERATOR_VERSION, RECIPE_VERSION
from .evaluation import evaluate, EVALUATOR_VERSION
from .methods import catalog, execute
from .synthetic import generate, practice_context


class SelfTrainingEngine:
    def __init__(self, repository, recipes, lesson_sink=None):
        self.repository, self.recipes = repository, recipes
        self.lesson_sink = lesson_sink
        self.stopping = threading.Event()

    def create(self, request):
        request = TrainingRequest.model_validate(request)
        sources = [self.recipes.for_asset(key) for key in request.source_asset_ids]
        if not sources:
            sources = self.recipes.list(20)
        if request.adaptive_start:
            supported = {item["context"] for item in self.evidence()
                         if item["validation_successes"] >= 3 and item["confidence"] >= .65}
            level = request.start_level
            while level < request.max_level and all(practice_context(level, recipe) in supported for recipe in sources or [None]):
                level += 1
            request = request.model_copy(update={"start_level": level})
        return self.repository.create(request, sources)

    def evidence(self):
        rows, groups = self.repository.attempts(limit=10000), {}
        for row in rows:
            if row["partition"] == "test":
                continue  # Locked test evidence cannot guide selection or promotion.
            key = (row["context"], row["method"]["id"])
            group = groups.setdefault(key, {"context": key[0], "method": row["method"], "observations": {}, "validation": {}})
            # Repeat/restart/renamed runs of the same generated world add no independent support.
            observations = group["observations"]
            observations.setdefault(row["independent_group"], row)
            if row["partition"] == "validation":
                group["validation"].setdefault(row["independent_group"], row)
        values = []
        for group in groups.values():
            observations, validation = list(group.pop("observations").values()), list(group.pop("validation").values())
            successes = sum(bool(r["evaluation"] and r["evaluation"]["passed"]) for r in validation)
            values.append({**group, "trials": len(observations), "mean_loss": sum(r["evaluation"]["loss"] if r["evaluation"] else 2. for r in observations)/len(observations),
                           "validation_trials": len(validation), "validation_successes": successes,
                           "confidence": (successes+1)/(len(validation)+2), "failures": sum(bool(r["error"] or not r["evaluation"]["passed"]) for r in observations),
                           "validation": "synthetic_validation_only", "professional_validated": False})
        return values

    def _select(self, methods, context, count, seed):
        evidence = {r["method"]["id"]: r for r in self.evidence() if r["context"] == context}
        champion = next((r["method"] for r in self.repository.champions() if r["context"] == context), None)
        selected = [methods[0]]  # Stable normalization comparator on every paired exercise.
        if champion and champion["id"] != selected[0]["id"] and any(m["id"] == champion["id"] for m in methods):
            selected.append(champion)
        rng = random.Random(seed)
        total = sum(r["trials"] for r in evidence.values())+1
        def priority(method):
            item = evidence.get(method["id"])
            if not item:
                return 100 + rng.random()
            return -item["mean_loss"]+ .15*math.sqrt(math.log(total+1)/item["trials"])
        ranked = sorted((m for m in methods if m["id"] not in {s["id"] for s in selected}), key=priority, reverse=True)
        result = []
        for method in (selected+ranked)[:count]:
            previous = evidence.get(method["id"])
            result.append({**method, "selection_basis": {"strategy": "normalization_comparator" if method["id"] == methods[0]["id"] else
                "retained_incumbent" if champion and method["id"] == champion["id"] else "uncertainty_bounded_exploration",
                "previous_independent_trials": previous["trials"] if previous else 0,
                "previous_mean_loss": previous["mean_loss"] if previous else None,
                "previous_failures": previous["failures"] if previous else 0, "test_evidence_used": False}})
        return result

    def _promote(self, context):
        rows = [r for r in self.repository.attempts(limit=10000) if r["context"] == context and r["partition"] == "validation"]
        by_group = {}
        for row in rows:
            by_group.setdefault(row["independent_group"], {}).setdefault(row["method"]["id"], row)
        champion = next((r for r in self.repository.champions() if r["context"] == context), None)
        candidate_ids = {r["method"]["id"] for r in rows}
        promotions = []
        for identifier in candidate_ids:
            wins, losses, references, method = 0, 0, [], None
            for group, items in by_group.items():
                row = items.get(identifier)
                incumbent = items.get(champion["method"]["id"]) if champion else next((r for r in items.values() if r["method"]["spec"]["binding"] == "preserve"), None)
                if not row or not incumbent or incumbent["method"]["id"] == identifier:
                    continue
                method = row["method"]
                if row["evaluation"] and row["evaluation"]["passed"] and (not incumbent["evaluation"] or row["evaluation"]["loss"] < incumbent["evaluation"]["loss"]-1e-6):
                    wins += 1
                    references.append(group)
                else:
                    losses += 1
            confidence = (wins+1)/(wins+losses+2)
            if wins >= 3 and confidence >= .65:
                promotions.append((confidence, wins, identifier, method, losses, references))
        if promotions:
            confidence, wins, _, method, losses, references = max(promotions, key=lambda v: (v[0], v[1], v[2]))
            promoted = self.repository.promote(context, method, {"paired_wins": wins, "paired_losses_or_ties": losses, "confidence": confidence,
                "independent_groups": references, "evaluator": EVALUATOR_VERSION, "test_data_used": False})
            if self.lesson_sink:
                self.lesson_sink(promoted)

    def _next_level(self, run, exercise):
        if exercise["partition"] == "test":
            return run["level"]
        prior = self.repository.exercises(run["id"])
        required = {practice_context(run["level"], recipe) for recipe in run["recipes"] or [None]}
        successes = {context: {e["independent_group"] for e in prior if e["level"] == run["level"] and e["context"] == context
                     and e["partition"] == "validation" and e.get("best_evaluation", {}).get("passed")} for context in required}
        if all(len(groups) >= 3 for groups in successes.values()):
            return min(run["request"]["max_level"], run["level"]+1)
        return run["level"]

    def run(self, identifier, exercises=1, seconds=120):
        if not 1 <= exercises <= 32 or not 1 <= seconds <= 300:
            raise ValueError("Training slice is bounded to 32 exercises/300 seconds.")
        run, token = self.repository.claim(identifier)
        if not token:
            return run
        versions = {"generator": GENERATOR_VERSION, "trainer": TRAINER_VERSION, "recipe": RECIPE_VERSION, "evaluator": EVALUATOR_VERSION}
        if run.get("versions") != versions:
            return self.repository.save(identifier, token, {"status": "paused_recovery", "recovery_reason": "Pipeline version changed; start a new run. Historical evidence is immutable."})
        deadline, completed = time.monotonic()+seconds, 0
        try:
            while completed < exercises and time.monotonic() < deadline:
                run = self.repository.get(identifier)
                if self.stopping.is_set() or run["pause_requested"] or run["cancel_requested"]:
                    return self.repository.save(identifier, token, {"status": "cancelled" if run["cancel_requested"] else "paused"})
                if run["completed_exercises"] >= run["request"]["max_exercises"]:
                    return self.repository.save(identifier, token, {"status": "completed", "ended_at": now()})
                if run["active_exercise"]:
                    exercise = self.repository.exercise(run["active_exercise"])
                else:
                    seed = (run["request"]["seed"]+run["completed_exercises"]*104729) % 2147483648
                    recipe = run["recipes"][run["completed_exercises"] % len(run["recipes"])] if run["recipes"] else None
                    initial, reference, metadata = generate(seed, run["level"], recipe)
                    # The partition is deterministic for a world, never decided by its score/run identity.
                    group = digest({"joints": [{"id": j["id"], "parent": j.get("parent"), "head": j["metadata"]["head"], "tail": j["metadata"]["tail"]} for j in reference["joints"]],
                                    "meshes": [{"positions": m["positions"], "faces": m["faces"]} for m in reference["meshes"]], "skins": reference["skins"]})
                    bucket = int(group[:8], 16) % 10
                    partition = "test" if bucket == 0 else "validation" if bucket < 5 else "train"
                    context = practice_context(run["level"], recipe)
                    methods = catalog(not initial["joints"], run["recipes"])
                    # Test worlds evaluate a frozen incumbent + a fixed comparator only. Never explore/promote from them.
                    if partition == "test":
                        champion = next((r["method"] for r in self.repository.champions() if r["context"] == context), methods[1])
                        selected = [methods[0], champion]
                    else:
                        selected = self._select(methods, context, run["request"]["candidates_per_exercise"], seed)
                    evaluation = evaluate(initial, reference, initial)
                    exercise = self.repository.begin_exercise(identifier, token, {"id": "exercise-"+uuid.uuid4().hex,
                        **metadata, "context": context, "independent_group": group, "partition": partition, "selected_methods": selected,
                        "baseline_evaluation": evaluation, "best_evaluation": evaluation, "best_method": None,
                        "current_expertise": {"recipe_ids": [r["id"] for r in run["recipes"]], "method_priors": [m["id"] for m in selected]},
                        "trainer": TRAINER_VERSION}, initial, reference)
                initial = self.repository.document(exercise["input_digest"])
                reference = self.repository.document(exercise["reference_digest"])
                while exercise["cursor"] < len(exercise["selected_methods"]):
                    control = self.repository.get(identifier)
                    if self.stopping.is_set() or control["pause_requested"] or control["cancel_requested"] or time.monotonic() > deadline:
                        return self.repository.save(identifier, token, {"status": "cancelled" if control["cancel_requested"] else "paused"})
                    method = exercise["selected_methods"][exercise["cursor"]]
                    candidate, quality, error = None, None, None
                    try:
                        candidate = execute(initial, method["spec"])
                        quality = evaluate(candidate, reference, initial)
                    except (ValueError, KeyError, ArithmeticError) as exc:
                        error = type(exc).__name__  # No source strings/paths/secrets in routine diagnostics.
                    accepted = bool(quality and quality["protected_data_intact"] and quality["missing_joint_fraction"] == 0 and quality["hierarchy_error"] == 0 and
                                    quality["normalization_max_error"] < 1e-6 and quality["loss"] < exercise["best_evaluation"]["loss"]-1e-8)
                    exercise = self.repository.attempt(identifier, token, exercise["id"], {"id": "attempt-"+uuid.uuid4().hex,
                        "exercise_id": exercise["id"], "run_id": identifier, "method": method, "decision": "paired exploration or retained incumbent",
                        "context": exercise["context"], "partition": exercise["partition"], "independent_group": exercise["independent_group"],
                        "input_digest": exercise["input_digest"], "knowledge": exercise["current_expertise"], "evaluation": quality, "error": error,
                        "accepted": accepted, "previous_best_digest": exercise["best_digest"], "previous_best_loss": exercise["best_evaluation"]["loss"],
                        "failure_analysis": {"protected_data": not quality["protected_data_intact"], "missing_joint_fraction": quality["missing_joint_fraction"],
                            "hierarchy_error": quality["hierarchy_error"], "weight_error": quality["weight_l1"], "pose_error": quality["pose_rm_distance"],
                            "joint_placement_error": quality["joint_error"], "normalization_error": quality["normalization_max_error"]} if quality else {"execution_error_category": error},
                        "correction": "next frozen alternative from the same immutable input" if not accepted else "keep measured best; retain previous checkpoint",
                        "synthetic": True, "at": now()}, candidate)
                experience = {"id": "experience-"+exercise["id"], "task_id": exercise["id"], "schema_version": 3,
                    "source_type": "character_self_training", "goal": "Reconstruct/improve synthetic production structures",
                    "synthetic": True, "context": {"run_id": identifier, "level": exercise["level"], "input_state": exercise["input_digest"]},
                    "retrieved_knowledge": exercise["current_expertise"], "steps": [r for r in self.repository.attempts(identifier, 1000) if r["exercise_id"] == exercise["id"]],
                    "result": exercise["best_digest"], "evaluation": exercise["best_evaluation"], "verified_success": exercise["best_evaluation"]["passed"],
                    "validation_scope": exercise["best_evaluation"]["scope"], "partition": exercise["partition"], "untrusted": True, "updated_at": now()}
                # Completion and its learning record commit together: a crash cannot lose the lesson.
                run = self.repository.finish_exercise(identifier, token, exercise["id"], self._next_level(run, exercise), experience)
                self._promote(exercise["context"])
                completed += 1
            return self.repository.save(identifier, token, {"status": "completed" if run["completed_exercises"] >= run["request"]["max_exercises"] else "paused"})
        except Exception:
            # Checkpoints are committed per attempt. An unexpected worker exception is visible, never silent success.
            try:
                self.repository.save(identifier, token, {"status": "paused_recovery", "recovery_reason": "Worker error; inspect attempts and resume explicitly."})
            except (ValueError, KeyError):
                pass
            raise

    def dataset(self, identifier, include_synthetic=False, limit=100):
        self.repository.get(identifier)
        if not include_synthetic:
            return {"records": [], "record_count": 0, "synthetic_excluded": True}
        exercises = {e["id"]: e for e in self.repository.exercises(identifier)}
        rows = []
        for attempt in self.repository.attempts(identifier, min(2048, limit)):
            exercise = exercises[attempt["exercise_id"]]
            rows.append({"schema_version": 1, "task": "character_production_workflow", "input_state": exercise["input_digest"],
                "knowledge_available": attempt["knowledge"], "decision": attempt["decision"], "actions": attempt["method"],
                "result": attempt["artifact_digest"], "quality": attempt["evaluation"], "failure": attempt["error"], "correction": attempt["correction"],
                "preferred": attempt["accepted"], "best_target": exercise["best_digest"], "analytic_reference": exercise["reference_digest"],
                "reference_label_type": "synthetic_generator_not_professional_ground_truth", "synthetic": True,
                "split": exercise["partition"], "split_group": exercise["independent_group"], "generator": exercise["generator"],
                "trainer": TRAINER_VERSION, "evaluator": EVALUATOR_VERSION, "source_recipe": exercise["recipe_id"],
                "provenance": {"run_id": identifier, "exercise_id": exercise["id"], "attempt_id": attempt["id"], "seed": exercise["seed"]}})
        return {"schema_version": 1, "records": rows, "record_count": len(rows), "synthetic_excluded": False,
                "limitations": ["Validation is online method-selection evidence, not a pristine test set.",
                                "Locked test rows never guide method selection, curriculum or promotion.",
                                "Different generator families and real professional holdouts are needed before broader claims."]}

    def shutdown(self):
        self.stopping.set()
