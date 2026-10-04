"""GLB validation/normalisation and the read-only FORM library contract.

The FORM contract test builds a library with FORM's own ``Projects`` class
(products/form/server) and the shared ``ProductionRepository``, then reads it
through Spatial Lab's adapter. If FORM changes its schema, this test fails.
"""

import asyncio
import hashlib
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

from app.expertise.production.contracts import BuildRequest
from app.expertise.production.repository import ProductionRepository
from app.expertise.store import ExpertiseStore, encode
from app.spatial import glb
from app.spatial.assets import AssetError, AssetRegistry
from app.spatial.fixtures import build_glb, calibration_fixture
from app.spatial.form_library import FormLibrary, FormLibraryError
from app.spatial.service import SpatialLabService

FORM_SERVER = Path(__file__).resolve().parents[2] / "products" / "form" / "server"
if str(FORM_SERVER) not in sys.path:
    sys.path.insert(0, str(FORM_SERVER))
from form_studio.projects import Projects  # noqa: E402  (FORM's real project aggregate)


def glb_with_json(document, binary=b""):
    payload = json.dumps(document).encode()
    payload += b" " * ((4 - len(payload) % 4) % 4)
    chunks = struct.pack("<I4s", len(payload), b"JSON") + payload
    if binary:
        chunks += struct.pack("<I4s", len(binary), b"BIN\x00") + binary
    return struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks


class GlbTests(unittest.TestCase):
    def test_inspection_reports_rig_clips_form_hud_and_bounds(self):
        data = build_glb(skinned=True, joint_count=4, clips=("Idle", "Walk Cycle"), hud_rings=3, form_style=True)
        info = glb.inspect(data)
        self.assertEqual(info["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(info["joints"], 4)
        self.assertEqual([c["name"] for c in info["clips"]], ["Idle", "Walk Cycle"])
        self.assertEqual(info["clips"][1]["duration"], 2.0)
        self.assertEqual(len(info["form_hud_nodes"]), 3)
        self.assertEqual(info["bounds"]["min"][1], 0.0)
        self.assertAlmostEqual(info["bounds"]["max"][1], 1.8, places=5)
        self.assertEqual(info["normalization"]["scale"], 1.0)
        self.assertIn("approximation", info["bounds_method"])

    def test_skinned_geometry_without_skin_is_flagged(self):
        data = build_glb(skinned=True, clips=("Idle",))
        info = glb.inspect(data)
        self.assertEqual(info["warnings"], [])
        document, binary = glb.parse_container(data)
        document["nodes"].append({"name": "stray", "mesh": 0})
        document["scenes"][0]["nodes"].append(len(document["nodes"]) - 1)
        payload = json.dumps(document).encode()
        payload += b" " * ((4 - len(payload) % 4) % 4)
        rebuilt = glb_with_json(json.loads(payload), bytes(binary))
        self.assertIn("without a skin", glb.inspect(rebuilt)["warnings"][0])

    def test_normalisation_handles_units_pivot_and_orientation_without_mutation(self):
        centimetres = glb.inspect(build_glb(size=(50, 180, 30), center=(0, 90, 0)))["normalization"]
        self.assertIn("rescaled_unit_mismatch", centimetres["flags"])
        self.assertAlmostEqual(centimetres["size"][1], 1.6, places=4)
        tiny = glb.inspect(build_glb(size=(0.01, 0.018, 0.003), center=(0, 0.009, 0)))["normalization"]
        self.assertIn("rescaled_tiny", tiny["flags"])
        offset = glb.inspect(build_glb(center=(3.0, 5.0, -2.0)))["normalization"]
        self.assertIn("pivot_recentered", offset["flags"])
        self.assertEqual(offset["offset"], [-3.0, -4.1, 2.0])
        lying = glb.inspect(build_glb(size=(0.5, 0.3, 1.8), center=(0, 0.15, 0)))["normalization"]
        self.assertIn("orientation_suspect_z_up", lying["flags"])

    def test_invalid_and_unsupported_files_are_rejected_with_reasons(self):
        good = build_glb()
        cases = {
            "not_glb": b"PK\x03\x04" + b"\x00" * 40,
            "corrupt": good[:-7],
            "unsupported_version": struct.pack("<4sII", b"glTF", 1, 20) + b"\x00" * 8,
            "missing_scene": build_glb(omit_scene=True),
            "unsupported_extension": build_glb(required_extensions=("KHR_draco_mesh_compression",)),
            "external_resource": glb_with_json({"asset": {"version": "2.0"}, "buffers": [{"byteLength": 4, "uri": "http://x/y.bin"}],
                                                "scenes": [{"nodes": []}]}),
            "invalid_reference": glb_with_json({"asset": {"version": "2.0"}, "scenes": [{"nodes": [3]}], "nodes": []}),
        }
        for code, data in cases.items():
            with self.subTest(code=code):
                with self.assertRaises(glb.GlbInvalid) as caught:
                    glb.inspect(data)
                self.assertEqual(caught.exception.code, code)
        cyclic = glb_with_json({"asset": {"version": "2.0"}, "scenes": [{"nodes": [0]}],
                                "nodes": [{"children": [1]}, {"children": [0]}]})
        with self.assertRaises(glb.GlbInvalid):
            glb.inspect(cyclic)
        empty = glb_with_json({"asset": {"version": "2.0"}, "scenes": [{"nodes": [0]}], "nodes": [{"name": "empty"}]})
        with self.assertRaises(glb.GlbInvalid) as caught:
            glb.inspect(empty)
        self.assertEqual(caught.exception.code, "no_geometry")


class FormLibraryContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "form-data"
        self.store = ExpertiseStore(self.root / "expert.sqlite3")
        self.production = ProductionRepository(self.store)
        self.projects = Projects(self.store, self.root / "projects")
        self.project = self.projects.create("AKASHI Hero", "brief")
        self.pid = self.project["id"]

    def version(self, data, *, verified=True, status="completed_partial", outside=False, record_sha=None):
        job = self.production.create(BuildRequest(brief="hero"), None, [])
        directory = (Path(self.temp.name) if outside else self.projects.directory(self.pid)) / "outputs"
        directory.mkdir(exist_ok=True)
        path = directory / (job["id"] + "-character.glb")
        path.write_bytes(data)
        job.update(status=status, application={
            "paths": {"glb": str(path)}, "done": ["export", "export_readback"],
            "export_readback": {"verified": verified, "sha256": record_sha or hashlib.sha256(data).hexdigest(),
                                "bytes": len(data), "skins": 1, "animations": 1}})
        with self.store.connection() as db:
            db.execute("UPDATE production_jobs SET body=? WHERE id=?", (encode(job), job["id"]))
        self.projects.link(self.pid, "production", job["id"])
        return job["id"], path

    def test_versions_follow_form_numbering_and_verification(self):
        first, _ = self.version(build_glb(skinned=True, clips=("Idle",)))
        second, _ = self.version(build_glb(), verified=False)
        third, _ = self.version(build_glb(), status="paused_recovery")
        fourth, _ = self.version(build_glb(), outside=True)
        fifth, _ = self.version(build_glb(size=(0.6, 1.9, 0.3)))
        self.projects.update(self.pid, {"best_run": first})
        library = FormLibrary(self.root)
        versions = library.versions(self.pid)
        self.assertEqual([v["label"] for v in versions], ["V01", "V02", "V03", "V04", "V05"])
        self.assertEqual([v["loadable"] for v in versions], [True, False, False, False, True])
        self.assertTrue(versions[0]["is_best"])
        self.assertNotIn("path", versions[0])
        self.assertEqual(library.resolve(self.pid, "latest")["id"], fifth)
        self.assertEqual(library.resolve(self.pid, "best")["id"], first)
        with self.assertRaises(FormLibraryError):
            library.resolve(self.pid, second)
        project = library.projects()[0]
        self.assertEqual((project["name"], project["versions"], project["loadable_versions"]), ("AKASHI Hero", 5, 2))

    def test_reading_never_modifies_form_and_identity_is_verified(self):
        run_id, path = self.version(build_glb(skinned=True, clips=("Idle",)))
        database = self.root / "expert.sqlite3"
        before = hashlib.sha256(database.read_bytes()).hexdigest()
        artifact_before = hashlib.sha256(path.read_bytes()).hexdigest()
        registry = AssetRegistry(Path(self.temp.name) / "spatial-assets", FormLibrary(self.root))
        summary = registry.register_form(self.pid, "latest")
        self.assertEqual(summary["form"]["version_label"], "V01")
        self.assertTrue(summary["form"]["identity_verified"])
        self.assertEqual(registry.content(summary["asset_id"]), path.read_bytes())
        self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), before)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), artifact_before)
        path.write_bytes(build_glb(size=(1, 1, 1)))  # artifact replaced after FORM verified it
        with self.assertRaises(AssetError) as caught:
            registry.register_form(self.pid, "latest")
        self.assertEqual(caught.exception.code, "identity_mismatch")
        with self.assertRaises(AssetError):
            registry.content(summary["asset_id"])

    def test_unavailable_or_foreign_library_fails_closed(self):
        self.assertFalse(FormLibrary(Path(self.temp.name) / "missing").status()["available"])
        foreign = Path(self.temp.name) / "foreign"
        foreign.mkdir()
        import sqlite3
        sqlite3.connect(foreign / "expert.sqlite3").execute("CREATE TABLE other(x)").connection.close()
        status = FormLibrary(foreign).status()
        self.assertEqual((status["available"], status["code"]), (False, "schema_mismatch"))

    def test_scene_switches_form_versions_and_keeps_provenance(self):
        v1, _ = self.version(build_glb(skinned=True, clips=("Idle",)))
        v2, _ = self.version(build_glb(size=(0.6, 1.9, 0.3), skinned=True, clips=("Idle", "Wave")))
        service = SpatialLabService(Path(self.temp.name) / "spatial", form_library=FormLibrary(self.root))
        session = service.create_session()["session"]["id"]
        outcome = asyncio.run(service.interpret(session, "Load the latest FORM version."))
        state = service.session(session).history.state
        obj = next(iter(state["objects"].values()))
        self.assertEqual(obj["asset"]["form"]["version_id"], v2)
        self.assertIn("identity verified", outcome["reply"])
        asyncio.run(service.interpret(session, "switch to the previous version"))
        obj = service.session(session).history.state["objects"][obj["id"]]
        self.assertEqual((obj["asset"]["form"]["version_id"], obj["label"]), (v1, "AKASHI Hero V01"))
        asyncio.run(service.interpret(session, "play the idle animation"))
        asyncio.run(service.interpret(session, "switch to v2"))
        obj = service.session(session).history.state["objects"][obj["id"]]
        self.assertEqual(obj["asset"]["form"]["version_label"], "V02")
        self.assertEqual(obj["animation"]["clip"], "Idle")
        self.assertTrue(service.verify_replay(session)["verified"])


class RegistryTests(unittest.TestCase):
    def test_uploads_are_content_addressed_and_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            registry = AssetRegistry(Path(temp), FormLibrary(None, candidates=[]))
            data = build_glb(clips=("Spin",))
            first = registry.register_upload(data, "My Robot.glb")
            second = registry.register_upload(data, "copy.glb")
            self.assertEqual(first["asset_id"], second["asset_id"])
            self.assertEqual(first["label"], "My Robot")
            self.assertEqual(len(list((Path(temp) / "uploads").glob("*.glb"))), 1)
            with self.assertRaises(AssetError):
                registry.register_upload(data, "robot.gltf")
            with self.assertRaises(AssetError) as caught:
                registry.register_upload(b"glTF" + b"\x00" * 30, "broken.glb")
            self.assertEqual(caught.exception.code, "unsupported_version")
            fixture = registry.register_fixture()
            self.assertEqual(registry.content(fixture["asset_id"]), calibration_fixture())
            reloaded = AssetRegistry(Path(temp), FormLibrary(None, candidates=[]))
            self.assertEqual({a["asset_id"] for a in reloaded.list()}, {first["asset_id"], fixture["asset_id"]})


if __name__ == "__main__":
    unittest.main()
