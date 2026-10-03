import copy
import json
import struct
import tempfile
import unittest
from pathlib import Path
from akashi_agent.actions import ActionExecutor
from akashi_agent.config import AgentSettings
from akashi_agent.production_export import validate_references


class ProductionAgentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.agent = ActionExecutor(
            AgentSettings(
                token="synthetic-test-token",
                allowed_roots=(self.root,),
                credential_file=self.root / "credential",
                capture_dir=self.root / "capture",
            )
        )

    def test_glb_uses_approved_paths_and_measured_buffer_correspondence(self):
        document = {
            "asset": {"version": "2.0"},
            "buffers": [{"byteLength": 36}],
            "bufferViews": [{"buffer": 0, "byteLength": 36}],
            "accessors": [
                {"bufferView": 0, "count": 3, "type": "VEC3", "componentType": 5126}
            ],
            "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        }
        payload = json.dumps(document).encode()
        payload += b" " * ((-len(payload)) % 4)
        data = struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(payload) + 8 + 36)
        data += struct.pack("<I4s", len(payload), b"JSON") + payload
        data += struct.pack("<I4s", 36, b"BIN\x00") + bytes(36)
        path = self.root / "synthetic.glb"
        path.write_bytes(data)
        result = self.agent.execute(
            "blender_operation",
            {"operation": "inspect_production_export", "project": str(path)},
            approved=True,
        )
        self.assertTrue(result["data"]["verified"])
        with self.assertRaises(PermissionError):
            self.agent.execute(
                "blender_operation",
                {"operation": "inspect_production_export", "project": str(path)},
            )
        with self.assertRaises(PermissionError):
            self.agent.execute(
                "blender_operation",
                {
                    "operation": "inspect_production_export",
                    "project": str(self.root.parent / "outside.glb"),
                },
                approved=True,
            )
        for mutate in (
            lambda v: v.update(images=[{"uri": "https://external.example/secret.png"}]),
            lambda v: v["accessors"][0].update(count=2000),
            lambda v: v["meshes"][0]["primitives"][0]["attributes"].update(POSITION=-1),
            lambda v: v.update(skins=[{"joints": [99]}]),
        ):
            malformed = copy.deepcopy(document)
            mutate(malformed)
            with self.assertRaises(ValueError):
                validate_references(malformed)

    def test_render_controls_are_bounded_not_arbitrary_camera_scripts(self):
        source = self.root / "scene.blend"
        source.write_bytes(b"synthetic-unit-placeholder")
        self.agent.apps["blender"] = "C:/synthetic/blender.exe"
        for args in ({"view": "run powershell"}, {"frame": 999}, {"frame": True}):
            with self.assertRaises(ValueError):
                self.agent.execute(
                    "blender_operation",
                    {
                        "operation": "render_production",
                        "project": str(source),
                        "output": str(self.root / "new.png"),
                        **args,
                    },
                    approved=True,
                )
        with self.assertRaises(ValueError):
            self.agent.execute(
                "blender_operation",
                {"operation": "inspect_scene", "project": str(source), "view": "Front"},
                approved=True,
            )
