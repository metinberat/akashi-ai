"""Host-specific fixed Blender operations, separate from the practice engine."""
import base64
import hashlib
import json
import math
import uuid
from pathlib import PureWindowsPath

from app.expertise.schema import CharacterDocument, Source
from app.expertise.store import now, encode


def compare_saved(expected, observed):
    """Read saved application data, not subprocess success or in-memory construction."""
    c = CharacterDocument.model_validate(observed)
    joints = {j.metadata.get("canonical_source_id"): j for j in c.joints}
    meshes = {m.metadata.get("canonical_source_id"): m for m in c.meshes}
    skins = {s.mesh_id: s for s in c.skins}
    ids = {j.id: j.metadata.get("canonical_source_id") for j in c.joints}
    maximum, vertices, weights_checked, uv_checked = 0., 0, 0, 0
    if set(joints) != {j["id"] for j in expected["joints"]} or set(meshes) != {m["id"] for m in expected["meshes"]}:
        raise ValueError("Saved construction has missing/unexpected source structures.")
    for joint in expected["joints"]:
        actual = joints[joint["id"]]
        if ids.get(actual.parent) != joint.get("parent"):
            raise ValueError("Saved hierarchy changed.")
        for field in ("head", "tail"):
            maximum = max(maximum, math.dist(actual.metadata[field], joint["metadata"][field]))
    source_skins = {s["mesh_id"]: s for s in expected["skins"]}
    for mesh in expected["meshes"]:
        actual = meshes[mesh["id"]]
        if actual.faces != mesh["faces"] or actual.positions is None or len(actual.positions) != len(mesh["positions"]):
            raise ValueError("Saved construction topology mismatch.")
        vertices += len(actual.positions)
        for a, b in zip(actual.positions, mesh["positions"]):
            maximum = max(maximum, math.dist(a,b))
        actual_skin = skins[actual.id]
        for a, b in zip(actual_skin.weights, source_skins[mesh["id"]]["weights"]):
            mapped = {ids[k]: v for k,v in a.items()}
            maximum = max(maximum, max(abs(mapped.get(k,0)-b.get(k,0)) for k in set(mapped)|set(b)))
            weights_checked += 1
        for name, values in mesh["metadata"].get("uv_coordinates", {}).items():
            readback = actual.metadata.get("uv_coordinates", {}).get(name)
            if readback is None or len(values) != len(readback):
                raise ValueError("Saved UV correspondence missing.")
            maximum = max(maximum, max((math.dist(a,b) for a,b in zip(values, readback)), default=0))
            uv_checked += len(values)
    return {"verified": maximum < 2e-5, "maximum_readback_error": maximum, "vertices": vertices,
            "weights_checked": weights_checked, "uv_loops_checked": uv_checked,
            "method": "new_saved_blend_reopened_and_structurally_compared", "synthetic": True}


class TrainingBlenderAdapter:
    def __init__(self, desktop, service):
        self.desktop, self.service = desktop, service
        with service.store.connection() as db:
            db.execute("CREATE TABLE IF NOT EXISTS training_application_evidence(id TEXT PRIMARY KEY,run_id TEXT NOT NULL,body TEXT NOT NULL)")

    async def action(self, **arguments):
        result = await self.desktop.execute("blender_operation", arguments, approved=True)
        if not result.get("ok") or not result.get("data", {}).get("verified"):
            raise RuntimeError("Fixed Blender operation failed or was not verified; no blind replay.")
        return result["data"]

    async def stage(self, value, output):
        payload = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode()
        if len(payload) > 32*1024*1024:
            raise ValueError("Construction artifact exceeds staging budget.")
        sha = hashlib.sha256(payload).hexdigest()
        chunks = [payload[i:i+24000].decode("ascii") for i in range(0, len(payload), 24000)]
        for i, chunk in enumerate(chunks):
            result = await self.action(operation="stage_character", output=output, chunk=chunk, chunk_index=i, chunk_count=len(chunks), sha256=sha)
        if not result.get("complete") or result.get("sha256") != sha:
            raise RuntimeError("Character staging did not complete.")
        return result

    async def read(self, project):
        offset, content, expected = 0, bytearray(), None
        while True:
            result = await self.action(operation="read_character_chunk", project=project, offset=offset, length=48000)
            identity = (result.get("sha256"), result.get("bytes"))
            if result.get("offset") != offset or (expected is not None and identity != expected) or not isinstance(identity[1], int) or not 0 < identity[1] <= 32*1024*1024:
                raise ValueError("Readback source changed or exceeds budget.")
            expected = identity
            chunk = base64.b64decode(result["data_base64"], validate=True)
            if not chunk or len(chunk) > 48000:
                raise ValueError("Invalid readback progress.")
            content.extend(chunk)
            offset += len(chunk)
            if len(content) > expected[1]:
                raise ValueError("Readback exceeds announced size.")
            if result.get("complete"):
                break
        if len(content) != expected[1] or hashlib.sha256(content).hexdigest() != expected[0]:
            raise ValueError("Readback digest mismatch.")
        return CharacterDocument.model_validate_json(content).model_dump(exclude_none=True)

    async def ingest_blender(self, project, output_directory, source):
        if not PureWindowsPath(project).is_absolute() or not PureWindowsPath(output_directory).is_absolute():
            raise ValueError("Source/output must be absolute approved Windows paths.")
        directory = PureWindowsPath(output_directory)
        output = str(directory/("character-inspection-"+uuid.uuid4().hex+".json"))
        result = await self.action(operation="inspect_character", project=project, output=output, timeout_seconds=150)
        observed = await self.read(output)
        observed["metadata"]["original_application_source_sha256"] = result["source_sha256"]
        # Original large binary stays in approved source storage; compact extraction is independently hashed.
        source = Source.model_validate(source)
        import asyncio
        return await asyncio.to_thread(self.service.ingest, "blender-extraction.json", json.dumps(observed).encode(), source)

    async def materialize(self, run_id, exercise_id, output_directory):
        if not PureWindowsPath(output_directory).is_absolute():
            raise ValueError("Output must be an absolute approved Windows directory.")
        exercise = self.service.training.repository.exercise(exercise_id)
        if exercise["run_id"] != run_id or exercise["status"] != "completed":
            raise ValueError("Only completed exercises from this run can be materialized.")
        if not exercise["best_evaluation"]["passed"]:
            raise ValueError("The synthetic best state did not meet its objective.")
        expected = self.service.training.repository.document(exercise["best_digest"])
        identity = uuid.uuid4().hex
        directory = PureWindowsPath(output_directory)
        paths = {"input": str(directory/(identity+"-input.json")), "blend": str(directory/(identity+"-best.blend")),
                 "inspection": str(directory/(identity+"-inspection.json")), "poses": str(directory/(identity+"-poses.json")), "render": str(directory/(identity+"-render.png"))}
        evidence = {"id": "training-app-"+identity, "run_id": run_id, "exercise_id": exercise_id, "best_digest": exercise["best_digest"],
                    "at": now(), "status": "unverified", "synthetic": True, "paths": paths}
        try:
            await self.stage(expected, paths["input"])
            evidence["construction"] = await self.action(operation="build_character", project=paths["input"], output=paths["blend"], timeout_seconds=150)
            await self.action(operation="inspect_character", project=paths["blend"], output=paths["inspection"], timeout_seconds=150)
            evidence["readback"] = compare_saved(expected, await self.read(paths["inspection"]))
            if not evidence["readback"]["verified"]:
                raise ValueError("Saved application readback does not match the best numeric state.")
            evidence["deformation"] = await self.action(operation="test_deformation", project=paths["blend"], output=paths["poses"], timeout_seconds=150)
            evidence["render"] = await self.action(operation="render_current", project=paths["blend"], output=paths["render"], timeout_seconds=150)
            evidence["status"] = "application_verified"
            evidence["scope"] = "saved structure/UV/weights verified and real Blender stress probes/render executed; artistic quality not certified"
            return evidence
        except Exception as exc:
            evidence.update(status="unverified", error_category=type(exc).__name__)
            raise
        finally:
            with self.service.store.connection() as db:
                db.execute("INSERT INTO training_application_evidence VALUES(?,?,?)", (evidence["id"], run_id, encode(evidence)))

    def evidence(self, run_id):
        self.service.training.repository.get(run_id)
        with self.service.store.connection() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT body FROM training_application_evidence WHERE run_id=? ORDER BY rowid", (run_id,))]
