import base64
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from akashi_agent.actions import ActionExecutor
from akashi_agent.config import AgentSettings
from akashi_agent.character_document import validate_document


def fixture():
    return {"schema_version": 1, "name": "SYNTHETIC triangle", "joints": [{"id": "test", "name": "test", "metadata": {"head": [0,0,0], "tail": [0,1,0]}}],
            "meshes": [{"id": "mesh", "name": "mesh", "vertex_count": 3, "positions": [[0,0,0],[1,0,0],[0,1,0]], "faces": [[0,1,2]], "skin_id": "skin"}],
            "skins": [{"id": "skin", "mesh_id": "mesh", "joints": ["test"], "weights": [{"test": 1}]*3}],
            "metadata": {"synthetic": True, "deformation_space": "shared_bind"}}


class CharacterAgentTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.agent = ActionExecutor(AgentSettings(token="synthetic-unit-token-000000000000000", allowed_roots=(self.root,), capture_dir=self.root/"capture", credential_file=self.root/"credential"))

    def test_typed_staging_and_chunk_readback_roundtrip(self):
        value = fixture()
        payload = json.dumps(value).encode()
        output = self.root/"character.json"
        chunks = [payload[:200].decode(), payload[200:].decode()]
        for i, chunk in enumerate(chunks):
            result = self.agent.execute("blender_operation", {"operation": "stage_character", "output": str(output), "chunk": chunk,
                "chunk_index": i, "chunk_count": 2, "sha256": hashlib.sha256(payload).hexdigest()}, approved=True)
        self.assertTrue(result["data"]["complete"])
        read = self.agent.execute("blender_operation", {"operation": "read_character_chunk", "project": str(output)}, approved=True)["data"]
        self.assertEqual(json.loads(base64.b64decode(read["data_base64"])), value)
        with self.assertRaises(PermissionError):
            self.agent.execute("blender_operation", {"operation": "read_character_chunk", "project": str(output)})
        with self.assertRaises(ValueError):
            self.agent.execute("blender_operation", {"operation": "read_character_chunk", "project": str(output), "length": 1000000}, approved=True)
        with self.assertRaises(ValueError):
            self.agent.execute("blender_operation", {"operation": "read_character_chunk", "project": str(output), "offset": True}, approved=True)

    def test_build_is_fixed_hidden_script_not_shell_or_asset_code(self):
        source = self.root/"synthetic.json"
        source.write_text(json.dumps(fixture()))
        output = self.root/"new.blend"
        def child(command, **kwargs):
            self.assertFalse(kwargs["shell"])
            self.assertIn("--disable-autoexec", command)
            self.assertIn("--factory-startup", command)
            self.assertNotIn("--python-expr", command)
            self.assertTrue(command[command.index("--python")+1].endswith("blender_bridge.py"))
            output.write_bytes(b"synthetic subprocess fixture")
            return type("Result", (), {"returncode": 0, "stderr": "", "stdout": 'AKASHI_BLENDER_RESULT={"verified":true}'})()
        with patch.dict(self.agent.apps, {"blender": "C:/synthetic/blender.exe"}), patch("akashi_agent.actions.subprocess.run", side_effect=child):
            self.assertTrue(self.agent.execute("blender_operation", {"operation": "build_character", "project": str(source), "output": str(output)}, approved=True)["data"]["verified"])

    def test_malformed_or_real_sources_are_not_silently_rebuilt(self):
        for mutate in (lambda d: d["metadata"].update(synthetic=False), lambda d: d["joints"][0].update(parent="test"),
                       lambda d: d["meshes"][0].update(morph_targets=["smile"]), lambda d: d["skins"][0].update(weights=[{"test": 2}]*3),
                       lambda d: d.update(command="run powershell")):
            doc = copy.deepcopy(fixture())
            mutate(doc)
            with self.assertRaises(ValueError):
                validate_document(doc, construction=True)
        arbitrary = self.root/"other.json"
        arbitrary.write_text('{"token":"not-a-character"}')
        with self.assertRaises(ValueError):
            self.agent.execute("blender_operation", {"operation": "read_character_chunk", "project": str(arbitrary)}, approved=True)
