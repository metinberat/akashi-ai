"""Bounded task-oriented supervised/preference views, with explicit label authority."""


def build(engine, run_id, view, budget=20000):
    if view not in {"weights", "joint_placement", "preferences"}:
        raise ValueError("Unsupported training dataset view.")
    rows, remaining = [], budget
    repo = engine.repository
    for exercise in repo.exercises(run_id):
        if exercise["status"] != "completed":
            continue
        base = {"schema_version": 1, "split": exercise["partition"], "split_group": exercise["independent_group"], "synthetic": True,
                "label_authority": "analytic_synthetic_generator_not_professional_truth", "generator": exercise["generator"],
                "knowledge_available": exercise["current_expertise"], "provenance": {"run": run_id, "exercise": exercise["id"], "source_recipe": exercise["recipe_id"]}}
        initial, reference = repo.document(exercise["input_digest"]), repo.document(exercise["reference_digest"])
        if view == "weights":
            source_meshes = {m["id"]: m for m in initial["meshes"]}
            for skin in reference["skins"]:
                mesh = source_meshes[skin["mesh_id"]]
                if mesh["vertex_count"] > remaining:
                    continue  # Whole meshes only; no broken vertex/weight index correspondence.
                remaining -= mesh["vertex_count"]
                rows.append({**base, "task": "skin_weight_reconstruction", "input": {"mesh": mesh,
                    "observed_skeleton": initial["joints"], "public_region_labels": initial["metadata"]["practice_descriptor"]},
                    "target": {"joint_palette": skin["joints"], "weights": skin["weights"]}, "reference": exercise["reference_digest"]})
        elif view == "joint_placement":
            count = sum(m["vertex_count"] for m in initial["meshes"])
            if count <= remaining:
                remaining -= count
                rows.append({**base, "task": "joint_placement", "input": {"geometry": initial["meshes"],
                    "public_region_labels": initial["metadata"]["practice_descriptor"], "observed_skeleton": initial["joints"]},
                    "target": reference["joints"], "reference": exercise["reference_digest"]})
        else:
            if not exercise["best_evaluation"]["passed"]:
                continue
            for attempt in repo.attempts(run_id, 2048):
                if attempt["exercise_id"] != exercise["id"] or not attempt["evaluation"] or not attempt["artifact_digest"] or attempt["artifact_digest"] == exercise["best_digest"]:
                    continue
                if attempt["evaluation"]["loss"] <= exercise["best_evaluation"]["loss"]+1e-8:
                    continue  # Do not fabricate a preference from a tie.
                rows.append({**base, "task": "measured_character_preference", "input": exercise["input_digest"],
                    "chosen": exercise["best_digest"], "rejected": attempt["artifact_digest"],
                    "chosen_quality": exercise["best_evaluation"], "rejected_quality": attempt["evaluation"],
                    "rejected_method": attempt["method"], "preference_authority": "numeric_objective_only_not_artist_preference"})
        if len(rows) >= 1000 or not remaining:
            break
    return {"view": view, "records": rows[:1000], "record_count": min(1000,len(rows)), "synthetic_excluded": False,
            "vertex_budget": budget, "vertices_used": budget-remaining,
            "limitations": ["Synthetic analytic targets are not learned professional expertise.", "Retain split_group across all views and re-exports.",
                            "Validate on independent generator families and real assets before making generalization claims."]}
