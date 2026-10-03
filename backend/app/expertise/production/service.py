import copy
import json
import uuid
from .contracts import BuildRequest, Design, CandidateSpec, VERSION, validate_colors
from .geometry import construct
from .evaluation import evaluate
from .repository import ProductionRepository
from app.expertise.store import now
from app.expertise.workshop.repository import digest
from app.memory.long_term import contains_sensitive_value


class ProductionEngine:
    def __init__(self, expertise):
        self.expertise = expertise
        self.repository = ProductionRepository(expertise.store)
        self.lesson_sink = None

    def create(self, request, reference=None):
        request = BuildRequest.model_validate(request)
        if contains_sensitive_value(request.brief):
            raise ValueError("Credential-like text cannot enter production records.")
        explicit = request.design is not None
        design = validate_colors(request.design or Design())
        request = request.model_copy(update={"design": design})
        sources = []
        if request.source_asset_id:
            asset = self.expertise.store.asset(request.source_asset_id)
            sources = [self.expertise.recipes.for_asset(asset["id"])]
        else:
            sources = self.expertise.recipes.list(10)
        return self.repository.create(
            request,
            reference
            or {
                "basis": "explicit design" if explicit else "local defaults",
                "unknown": [
                    "back/side reference",
                    "hidden anatomy",
                    "target-engine constraints",
                    "visual similarity",
                ],
                "fidelity": "unmeasured",
                "assumptions": "stylized humanoid fallback; no image was analyzed",
            },
            {
                "recipe_ids": [r["id"] for r in sources],
                "method_evidence": self.repository.lessons(),
                "weight_priors": [
                    {
                        "version": r["id"],
                        "spec": r["method"]["spec"],
                        "scope": r["scope"],
                        "evidence": r["evidence"],
                    }
                    for r in self.expertise.training.repository.champions()
                    if r["evidence"].get("paired_wins", 0) >= 3
                ],
                "untrusted": True,
            },
        )

    def candidate(self, job):
        previous = self.repository.trials(job["id"])
        method = CandidateSpec(radial=8, clearance=0.006)
        priors = job["expertise"].get("weight_priors", [])
        if priors:
            prior = max(priors, key=lambda r: r["evidence"].get("confidence", 0))
            method = method.model_copy(
                update={
                    "distance_power": max(1, min(4, prior["spec"]["distance_power"]))
                }
            )
        if previous:
            last = previous[-1]
            method = CandidateSpec.model_validate(last["method"])
            defects = last["evaluation"]["defects"] if last.get("evaluation") else []
            method = method.model_copy(
                update={
                    "radial": min(32, method.radial + 8),
                    "clearance": max(0.012, method.clearance)
                    if "insufficient_declared_garment_clearance" in defects
                    else method.clearance,
                }
            )
        else:
            known = [
                r
                for r in job["expertise"]["method_evidence"]
                if r["independent_worlds"] >= 3 and r["confidence"] >= 0.65
            ]
            if known:
                method = CandidateSpec.model_validate(
                    min(known, key=lambda r: r["mean_loss"])["method"]
                )
        document = construct(
            job["request"]["design"], method.model_dump(), job["request"]["seed"]
        )
        quality = evaluate(document)
        return {
            "id": "production-trial-" + uuid.uuid4().hex,
            "method": method.model_dump(),
            "evaluation": quality,
            "independent_world": digest(
                {
                    "joints": document["joints"],
                    "meshes": [
                        {"positions": m["positions"], "family": m["metadata"]["family"]}
                        for m in document["meshes"]
                    ],
                }
            ),
            "synthetic": True,
            "knowledge": job["expertise"],
            "decision": "prior independently supported method"
            if not previous and method.radial != 8
            else "bounded correction from measured defects",
            "application": None,
            "accepted": False,
            "at": now(),
        }, document

    def publish_lessons(self):
        # Compact computed evidence only. Raw references and user briefs never enter RAG.
        for lesson in self.repository.lessons():
            if lesson["independent_worlds"] < 3 or lesson["confidence"] < 0.65:
                continue
            identifier = "production-method:" + digest(lesson["method"])
            self.expertise.knowledge.ingest(
                "Synthetic full-character authoring method",
                json.dumps(lesson, sort_keys=True),
                source=identifier,
                kind="character_production_evidence",
                metadata={
                    "category": "computed_metric",
                    "synthetic": True,
                    "authority": "local_numeric_evaluator",
                    "validation": "not_professional",
                    "confidence": lesson["confidence"],
                    "version": VERSION,
                },
            )
            if self.lesson_sink:
                self.lesson_sink(identifier, lesson)

    def numeric(self, key, steps=6):
        if not 1 <= steps <= 6:
            raise ValueError("Bounded production steps required.")
        job, token = self.repository.claim(key)
        if not token:
            return job
        try:
            if job["version"] != VERSION:
                raise ValueError("Production version changed; create a fresh job.")
            if job["mode"] != "procedural_character":
                return self.repository.save(
                    key,
                    token,
                    {
                        "status": "awaiting_application_source",
                        "requirements": [
                            "approved .blend source and desktop execution"
                        ],
                    },
                    release=True,
                )
            for _ in range(steps):
                control = self.repository.get(key)
                if control["pause_requested"] or control["cancel_requested"]:
                    return self.repository.save(
                        key,
                        token,
                        {
                            "status": "cancelled"
                            if control["cancel_requested"]
                            else "paused"
                        },
                        release=True,
                    )
                if job["cursor"] >= job["request"]["max_candidates"]:
                    break
                trial, doc = self.candidate(job)
                trial["document_digest"] = digest(doc)
                accepted = trial["evaluation"]["passed"] and (
                    not job["best"]
                    or trial["evaluation"]["loss"]
                    < job["best"]["evaluation"]["loss"] - 1e-8
                )
                trial["accepted"] = bool(accepted)
                best = copy.deepcopy(trial) if accepted else job["best"]
                experience = {
                    "id": "experience-" + trial["id"],
                    "task_id": trial["id"],
                    "schema_version": 3,
                    "source_type": "character_production",
                    "synthetic": True,
                    "goal": job["request"]["brief"],
                    "retrieved_knowledge": job["expertise"],
                    "result": trial["document_digest"],
                    "evaluation": trial["evaluation"],
                    "verified_success": False,
                    "validation_scope": "numeric authoring only; application pending",
                    "corrections": trial["evaluation"]["defects"],
                    "updated_at": now(),
                }
                job = self.repository.save(
                    key,
                    token,
                    {"cursor": job["cursor"] + 1, "best": best, "status": "correcting"},
                    trial=trial,
                    document=doc,
                    experience=experience,
                )
            result = self.repository.save(
                key,
                token,
                {"status": "numeric_ready" if job["best"] else "needs_correction"},
                release=True,
            )
            self.publish_lessons()
            return result
        except Exception:
            # A publication failure after commit must not overwrite a durable best state.
            current = self.repository.get(key)
            if current.get("lease") == token:
                self.repository.save(
                    key, token, {"status": "paused_recovery"}, release=True
                )
            raise

    def practice(self, count=3, seed=57):
        if not 1 <= count <= 12:
            raise ValueError("Practice is bounded to twelve characters.")
        jobs = []
        for i in range(count):
            design = Design(
                height=1.5 + (i % 4) * 0.15,
                head_ratio=0.12 + (i % 4) * 0.025,
                shoulder_ratio=0.21 + (i % 4) * 0.035,
                build=("slender", "balanced", "strong")[i % 3],
                clothing=("bodysuit", "coat", "armor")[i % 3],
                hair=("none", "short", "long")[i % 3],
                hud=i % 2 == 1,
            )
            job = self.create(
                BuildRequest(
                    brief="SYNTHETIC full-character authoring practice",
                    design=design,
                    seed=(seed + i * 104729) % (2**31),
                )
            )
            jobs.append(self.numeric(job["id"]))
        return {
            "jobs": jobs,
            "lessons": self.repository.lessons(),
            "scope": "geometry/topology/appearance authoring practice; real DCC verification is separate",
        }

    def dataset(self, key):
        job = self.repository.get(key)
        return {
            "synthetic": job["mode"] == "procedural_character",
            "records": [
                {
                    "input": job["request"]["design"],
                    "knowledge": r["knowledge"],
                    "decision": r["decision"],
                    "method": r["method"],
                    "result": r["document_digest"],
                    "quality": r["evaluation"],
                    "accepted": r["accepted"],
                    "best_target": job["best"]["document_digest"]
                    if job["best"]
                    else None,
                    "split_group": r["independent_world"],
                    "label_authority": "computed synthetic geometry metrics; not artist preference",
                }
                for r in self.repository.trials(key)
            ],
        }
