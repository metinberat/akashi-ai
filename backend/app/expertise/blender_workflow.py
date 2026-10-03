"""Host adapter: existing authenticated Windows Agent, never arbitrary Python.

Domain internals stay in workshop/. This transport is intentionally replaceable.
"""
import asyncio
import hashlib
import json
import uuid
from pathlib import PureWindowsPath

from app.expertise.workshop.application import ApplicationEvidence, compare_application


class BlenderWorkshopWorkflow:
    def __init__(self, desktop, workshop):
        self.desktop, self.workshop = desktop, workshop

    async def refine(self, identifier, project, output_directory, max_cycles=3):
        """One explicit approval covers bounded, non-destructive quality correction.

        An actual application rejection can trigger another numeric plan. Transport
        failure cannot: the remote operation may still be running, so replay would
        be unsafe. Each application result and numeric checkpoint remains durable.
        """
        if type(max_cycles) is not int or not 1 <= max_cycles <= 3:
            raise ValueError("Application refinement permits one to three verification cycles.")
        if not PureWindowsPath(project).is_absolute() or not PureWindowsPath(output_directory).is_absolute():
            raise ValueError("Application paths must be absolute approved Windows paths.")
        repo, cycles = self.workshop.repository, []
        for _ in range(max_cycles):
            state = await asyncio.to_thread(repo.get, identifier)
            if self.workshop.stopping.is_set() or state["cancel_requested"]:
                raise ValueError("Character refinement interrupted; source and checkpoints retained.")
            if state["status"] != "completed":
                await asyncio.to_thread(self.workshop.run, identifier)
            # This holds a fenced application lease and verifies saved results.
            # Failures without actual pose evidence propagate rather than replay.
            verification = await self.materialize(identifier, project, output_directory)
            cycles.append(verification)
            if verification["evidence"]["accepted"]:
                return {"status": "verified", "cycles": cycles, "best_version": verification["best_version"],
                        "quality_scope": "saved_weights_and_actual_numeric_pose_tests_not_artistic_certification"}
            state = await asyncio.to_thread(repo.get, identifier)
            if (not str(verification["evidence"].get("scope", "")).startswith("actual_application")
                or state["attempts"] >= state["max_attempts"] or state["next_proposal"] >= len(state["proposals"])):
                break
        state = await asyncio.to_thread(repo.get, identifier)
        return {"status": "needs_review", "cycles": cycles, "best_version": state["best_version"],
                "quality_scope": "application_rejected_or_cycle_budget_exhausted_no_verified_output_claim"}

    async def materialize(self, identifier, project, output_directory):
        if not PureWindowsPath(project).is_absolute() or not PureWindowsPath(output_directory).is_absolute():
            raise ValueError("Application paths must be absolute approved Windows paths.")
        repo = self.workshop.repository
        previous = await asyncio.to_thread(repo.get, identifier)
        if previous["cancel_requested"]:
            raise ValueError("Cancelled improvement cannot materialize an artifact.")
        job, token = await asyncio.to_thread(repo.claim, identifier, True)
        version_id = job["best_version"]
        directory = PureWindowsPath(output_directory)
        prefix = "akashi-character-" + uuid.uuid4().hex[:16]
        artifacts = {key: str(directory/(prefix+suffix)) for key, suffix in
                     (("patch", "-weights.json"), ("output", ".blend"),
                      ("readback", "-readback.json"), ("before", "-before-poses.json"), ("after", "-after-poses.json"))}

        async def execute(action, arguments):
            if self.workshop.stopping.is_set() or (await asyncio.to_thread(repo.get, identifier))["cancel_requested"]:
                raise ValueError("Character workflow interrupted; source file is unchanged.")
            result = await self.desktop.execute(action, arguments, True)
            if not isinstance(result, dict) or result.get("ok") is False:
                raise ValueError("Application action failed.")
            await asyncio.to_thread(repo.checkpoint, identifier, token, {})
            return result.get("data", result)

        async def inspect(operation, source, output):
            await execute("blender_operation", {"operation": operation, "project": source, "output": output, "timeout_seconds": 90})
            result = await execute("read_text_file", {"path": output, "max_chars": 2_000_000})
            if result.get("truncated"):
                raise ValueError("Application evidence exceeds the bounded Agent text bridge; use a compact/streaming adapter for this asset.")
            content = result.get("content") or result.get("text")
            if not isinstance(content, str):
                raise ValueError("Application evidence was not readable.")
            return json.loads(content)

        try:
            patch = await asyncio.to_thread(self.workshop.weight_patch, identifier)
            content = json.dumps(patch, allow_nan=False)
            if len(content.encode()) > 32*1024*1024:
                raise ValueError("Weight patch exceeds 32 MiB. Partition the asset through a specialized adapter.")
            # The app adapter checks this fingerprint again immediately before editing.
            if len(content) <= 60000:
                await execute("file_operation", {"operation": "create_text", "destination": artifacts["patch"], "content": content, "overwrite": False})
            else:
                chunks = [content[i:i+24000] for i in range(0, len(content), 24000)]
                sha256 = hashlib.sha256(content.encode()).hexdigest()
                last = None
                for index, chunk in enumerate(chunks):
                    last = await execute("blender_operation", {"operation": "stage_weights", "output": artifacts["patch"], "chunk": chunk,
                        "chunk_index": index, "chunk_count": len(chunks), "sha256": sha256})
                if not last or not last.get("complete") or last.get("sha256") != sha256:
                    raise ValueError("Character patch staging did not produce verified bytes.")
            applied = await execute("blender_operation", {"operation": "apply_weights", "project": project, "output": artifacts["output"], "patch": artifacts["patch"], "timeout_seconds": 90})
            if not applied.get("source_preserved") or not applied.get("source_sha256"):
                raise ValueError("Application did not verify source preservation.")
            await execute("blender_operation", {"operation": "verify_weights", "project": artifacts["output"], "output": artifacts["readback"], "patch": artifacts["patch"], "timeout_seconds": 90})
            verification = await execute("read_text_file", {"path": artifacts["readback"], "max_chars": 10000})
            readback = json.loads(verification.get("content", "{}"))
            if not readback.get("verified") or readback.get("version_id") != version_id or readback.get("max_weight_error", 1) > 1e-6:
                raise ValueError("Saved application weights do not match the best checkpoint.")
            before = ApplicationEvidence.model_validate(await inspect("test_deformation", project, artifacts["before"]))
            after = ApplicationEvidence.model_validate(await inspect("test_deformation", artifacts["output"], artifacts["after"]))
            evidence = compare_application(before, after)
            evidence.update(artifacts=artifacts, readback=readback, source_sha256=applied["source_sha256"], authority="authenticated_fixed_agent_adapter_with_saved_file_readback")
            await asyncio.to_thread(repo.attach_application_evidence, identifier, version_id, evidence, token)
            state = "paused_recovery" if not evidence["accepted"] else "completed" if previous["status"] == "completed" else "paused"
            await asyncio.to_thread(repo.checkpoint, identifier, token, {"status": state, "application_artifacts": artifacts})
            await asyncio.to_thread(self.workshop._experience, repo.get(identifier))
            return {"version_id": version_id, "source_preserved": True, "evidence": evidence, "best_version": repo.get(identifier)["best_version"]}
        except BaseException:
            # An unverified output may remain for inspection. Never designate it as best.
            evidence = {"accepted": False, "reasons": ["Application verification failed or was interrupted."], "scope": "application_transport_or_readback_failure", "authority": "fixed_adapter_failure", "artifacts": artifacts}
            await asyncio.to_thread(repo.attach_application_evidence, identifier, version_id, evidence, token)
            await asyncio.to_thread(repo.checkpoint, identifier, token, {"status": "paused_recovery", "pause_reason": "Application output not accepted. Source and baseline preserved."})
            raise
