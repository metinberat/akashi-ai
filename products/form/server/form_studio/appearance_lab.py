"""Project-owned visual practice: real DCC trials, measured proxies, reversible designs.

Independent of Core and optional providers. Does not claim neural training or
professional likeness. Only repeated independent reference evidence enters RAG.
"""

import asyncio
import copy
import json
import uuid
from pathlib import Path

from app.expertise.production.contracts import Design
from app.expertise.production.visual import analyze, compare, propose, VISUAL_VERSION
from app.expertise.store import now


class AppearanceLab:
    def __init__(self, engine):
        self.engine = engine
        self.worker = None
        self.stopping = False

    def assess(self, key, run_id, reference_id):
        e = self.engine
        e.projects.require_link(key, "production", run_id)
        reference, record = e.projects.resolve_file(key, reference_id)
        if record["kind"] != "reference":
            raise ValueError("Visual assessment requires an uploaded reference image.")
        run = e.domain.production.repository.get(run_id)
        app = run.get("application") or {}
        if (
            run["status"] != "completed_partial"
            or "front" not in app.get("done", [])
            or "export_readback" not in app.get("done", [])
        ):
            raise ValueError(
                "Visual assessment requires a completed, verified front render/export."
            )
        render = Path(app["paths"]["front"])
        if not render.resolve().is_relative_to(e.projects.directory(key).resolve()):
            raise ValueError("Render is outside the project.")
        value = compare(reference.read_bytes(), render.read_bytes())
        value.update(
            run_id=run_id,
            reference_id=reference_id,
            at=now(),
            synthetic_output=run["mode"] == "procedural_character",
            design=run["request"]["design"],
            features_verified=app.get("features", {}).get("verified", False),
        )
        project = e.projects.get(key)
        rows = project.get("visual_evaluations", [])
        rows = [
            r
            for r in rows
            if (r["run_id"], r["reference_id"]) != (run_id, reference_id)
        ]
        e.projects.update(key, {"visual_evaluations": (rows + [value])[-100:]})
        return value

    async def start(self, key, reference_id, attempts=2, resume=False):
        e = self.engine
        async with e.commands:
            if self.worker and not self.worker.done():
                raise ValueError("Visual practice is already running.")
            if e.shape.worker and not e.shape.worker.done():
                raise ValueError(
                    "Wait for the local shape experiment before visual practice."
                )
            if e.production.worker and not e.production.worker.done():
                raise ValueError("Wait or pause the current production first.")
            if (
                e.domain.training_host.worker
                and not e.domain.training_host.worker.done()
            ):
                raise ValueError("Wait or pause current rig training first.")
            project = e.projects.get(key)
            if resume:
                lab = project.get("visual_lab")
                if not lab or lab["status"] not in {"paused", "paused_recovery"}:
                    raise ValueError("No resumable visual practice.")
            else:
                path, record = e.projects.resolve_file(key, reference_id)
                if record["kind"] != "reference" or not 1 <= attempts <= 3:
                    raise ValueError("A reference and 1–3 bounded trials are required.")
                observation = analyze(path.read_bytes())
                if observation["mask_status"] != "measured":
                    raise ValueError(
                        "Visual practice needs a separable foreground/alpha reference. Complex-background images can still be discussed and built locally."
                    )
                original = Design.model_validate(
                    project.get("design") or {}
                ).model_dump()
                fitted = Design.model_validate(
                    propose(original, observation)
                ).model_dump()
                lab = {
                    "id": uuid.uuid4().hex,
                    "version": VISUAL_VERSION,
                    "reference_id": reference_id,
                    "reference_sha256": observation["image_sha256"],
                    "original_design": original,
                    "candidates": [original, fitted][:attempts],
                    "cursor": 0,
                    "attempts": [],
                    "best": None,
                    "created_at": now(),
                    "scope": "synthetic image-proxy practice; not professional likeness or neural fine-tuning",
                }
                if attempts == 3:
                    adapted = copy.deepcopy(fitted)
                    adapted["cloth_color"] = [
                        min(1, c * 0.8) for c in fitted["cloth_color"]
                    ]
                    lab["candidates"].append(adapted)
                # Best of prior actual versions is a baseline, never discarded by a bad experiment.
                for run_id in e.projects.links(key, "production")[-6:]:
                    run = e.domain.production.repository.get(run_id)
                    if (
                        run["status"] != "completed_partial"
                        or run["mode"] != "procedural_character"
                    ):
                        continue
                    value = self.assess(key, run_id, reference_id)
                    if value["loss"] is not None and (
                        not lab["best"] or value["loss"] < lab["best"]["loss"]
                    ):
                        lab["best"] = value
            lab.update(
                status="running",
                pause_requested=False,
                cancel_requested=False,
                updated_at=now(),
            )
            e.projects.update(key, {"visual_lab": lab})
            self.worker = asyncio.create_task(self.run(key))
            return lab

    def control(self, key, command):
        project = self.engine.projects.get(key)
        lab = project.get("visual_lab")
        if not lab or lab["status"] not in {"running", "paused", "paused_recovery"}:
            raise ValueError("No active visual practice.")
        lab[command + "_requested"] = True
        if lab["status"] != "running" and command == "cancel":
            lab["status"] = "cancelled"
        self.engine.projects.update(key, {"visual_lab": lab})
        return lab

    def save(self, key, lab, **changes):
        control = self.engine.projects.get(key).get("visual_lab", {})
        lab.update(
            pause_requested=control.get("pause_requested", False),
            cancel_requested=control.get("cancel_requested", False),
        )
        lab.update(changes, updated_at=now())
        self.engine.projects.update(key, {"visual_lab": lab})

    async def run(self, key):
        e = self.engine
        lab = e.projects.get(key)["visual_lab"]
        try:
            path, _ = e.projects.resolve_file(key, lab["reference_id"])
            if (
                analyze(path.read_bytes())["image_sha256"] != lab["reference_sha256"]
                or lab["version"] != VISUAL_VERSION
            ):
                raise ValueError(
                    "Reference or evaluator changed; create a fresh experiment."
                )
            while lab["cursor"] < len(lab["candidates"]):
                control = e.projects.get(key)["visual_lab"]
                if (
                    self.stopping
                    or control["pause_requested"]
                    or control["cancel_requested"]
                ):
                    self.save(
                        key,
                        lab,
                        status="cancelled" if control["cancel_requested"] else "paused",
                    )
                    return
                run_id = lab.get("pending_run")
                if run_id:
                    run = e.domain.production.repository.get(run_id)
                    if run["status"] in {"paused", "paused_recovery", "planned"}:
                        if (run.get("active_application") or {}).get("inflight"):
                            raise ValueError(
                                "Reconcile ambiguous DCC effects before resuming the experiment."
                            )
                        await e.production.start(run_id)
                else:
                    e.projects.update(key, {"design": lab["candidates"][lab["cursor"]]})
                    run = await e.build(key, visual_practice=True)
                    run_id = run["id"]
                    self.save(key, lab, pending_run=run_id)
                if e.production.worker and not e.production.worker.done():
                    await e.production.worker
                run = e.domain.production.repository.get(run_id)
                if run["status"] != "completed_partial":
                    self.save(
                        key,
                        lab,
                        status="paused_recovery",
                        reason="Production is not verified; inspect/reconcile its receipts.",
                    )
                    return
                value = self.assess(key, run_id, lab["reference_id"])
                accepted = (
                    value["loss"] is not None
                    and value["features_verified"]
                    and (not lab["best"] or value["loss"] < lab["best"]["loss"] - 1e-6)
                )
                lab["attempts"].append(
                    {
                        "evaluation": value,
                        "accepted": accepted,
                        "decision": "measured proxy improved"
                        if accepted
                        else "no improvement; preserved prior best",
                        "synthetic": True,
                    }
                )
                if accepted:
                    lab["best"] = value
                self.save(key, lab, cursor=lab["cursor"] + 1, pending_run=None)
            self.save(key, lab, status="completed")
            self.publish(key, lab)
        except Exception as exc:
            self.save(
                key,
                lab,
                status="paused_recovery",
                error_category=type(exc).__name__,
                reason="Saved experiment retained. Inspect verified artifacts before resuming.",
            )
        finally:
            e.projects.update(
                key,
                {
                    "design": (
                        lab["best"]["design"]
                        if lab.get("best")
                        else lab["original_design"]
                    )
                },
            )

    def publish(self, key, lab):
        e = self.engine
        # RAG receives measured experiments with provenance, NOT authoritative instructions.
        compact = {
            "id": lab["id"],
            "reference_sha256": lab["reference_sha256"],
            "version": lab["version"],
            "attempts": lab["attempts"],
            "best": lab["best"],
            "scope": lab["scope"],
        }
        e.domain.knowledge.ingest(
            "Local appearance practice evidence",
            json.dumps(compact),
            source="form-appearance:" + lab["id"],
            kind="character_appearance_evidence",
            metadata={
                "synthetic": True,
                "validation": "image_proxy_only",
                "authority": "local_pixel_evaluator",
                "category": "computed_metric",
                "confidence": 0.3,
                "version": VISUAL_VERSION,
            },
        )
        e.projects.message(
            key,
            "engine",
            "Visual practice completed. Real render comparisons and rejected attempts retained. Best proxy state preserved; artistic fidelity remains unproven.",
        )

    async def shutdown(self):
        self.stopping = True
        # Production shutdown marks pause at a safe boundary; then the lab can checkpoint.
        await self.engine.production.shutdown()
        if self.worker and not self.worker.done():
            await self.worker
