"""Spatial Lab scene domain, compiler, reference resolution and language rules."""

import asyncio
import math
import tempfile
import unittest
from pathlib import Path

from app.history.engine import CommandRejected
from app.spatial.domain import SpatialSceneDomain
from app.spatial.form_library import FormLibrary
from app.spatial.geometry import axis_angle, canonical_quat, rotate_world, yaw_degrees
from app.spatial.language import RuleInterpreter, parse_model_output
from app.spatial.model import LIMITS, initial_scene, summarize
from app.spatial.references import Clarification, resolve
from app.spatial.requests import ObjectRef, parse_request
from app.spatial.service import RequestInvalid, SpatialLabService

UI = {"kind": "ui", "provider": "test"}


def run(coroutine):
    return asyncio.run(coroutine)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class SpatialFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = Clock()
        self.service = SpatialLabService(Path(self.temp.name), form_library=FormLibrary(None, candidates=[]), monotonic=self.clock)
        self.session_id = self.service.create_session("Test")["session"]["id"]

    def submit(self, request, origin=UI, **options):
        return run(self.service.submit(self.session_id, request, origin, **options))

    def add(self, x=None, label=None):
        request = {"type": "scene.add_asset", "fixture": "calibration"}
        if x is not None:
            request["position"] = [x, 0, 0]
        if label:
            request["label"] = label
        return self.submit(request)["targets"][0]

    @property
    def state(self):
        return self.service.session(self.session_id).history.state

    def say(self, text):
        return run(self.service.interpret(self.session_id, text))


class GeometryTests(unittest.TestCase):
    def test_quaternion_canonical_sign_and_yaw(self):
        q = canonical_quat([0, -1, 0, 0])
        self.assertEqual(q, [0.0, 1.0, 0.0, 0.0])
        self.assertAlmostEqual(yaw_degrees(rotate_world([0, 0, 0, 1], "y", 90)), 90.0, places=2)
        full = rotate_world(rotate_world([0, 0, 0, 1], "y", 180), "y", 180)
        self.assertEqual(full, [0.0, 0.0, 0.0, 1.0])
        with self.assertRaises(ValueError):
            canonical_quat([0, 0, 0, 0])
        self.assertAlmostEqual(math.sqrt(sum(v * v for v in axis_angle("x", 33))), 1.0)


class ReducerTests(SpatialFixture):
    def test_reducer_rejects_out_of_bounds_and_invalid_transforms(self):
        object_id = self.add()
        domain = SpatialSceneDomain()
        state = self.state
        bad = [
            {"position": [99, 0, 0], "rotation": [0, 0, 0, 1], "scale": 1},
            {"position": [0, 0, 0], "rotation": [0, 0, 0, 2], "scale": 1},
            {"position": [0, 0, 0], "rotation": [0, 0, 0, 1], "scale": 50},
            {"position": [0, 0], "rotation": [0, 0, 0, 1], "scale": 1},
            {"position": [0, 0, 0], "rotation": [0, 0, 0, 1], "scale": 1, "extra": 1},
        ]
        for transform in bad:
            with self.assertRaises(CommandRejected):
                domain.apply(state, {"type": "object.transform", "object_id": object_id, "transform": transform})

    def test_display_flags_respect_asset_capabilities(self):
        object_id = self.add()
        self.submit({"type": "object.display", "target": {"id": object_id}, "skeleton": True})
        self.assertTrue(self.state["objects"][object_id]["display"]["skeleton"])
        with self.assertRaises(CommandRejected) as caught:
            self.submit({"type": "object.display", "target": {"id": object_id}, "form_hud": True})
        self.assertEqual(caught.exception.code, "no_form_hud")

    def test_scene_capacity_and_unknown_command(self):
        for _ in range(LIMITS["max_objects"]):
            self.add()
        with self.assertRaises(CommandRejected) as caught:
            self.add()
        self.assertEqual(caught.exception.code, "scene_full")
        with self.assertRaises(CommandRejected):
            SpatialSceneDomain().apply(initial_scene(), {"type": "object.explode"})

    def test_placement_is_deterministic_and_non_overlapping(self):
        first, second = self.add(), self.add()
        a, b = self.state["objects"][first], self.state["objects"][second]
        self.assertEqual(a["transform"]["position"], [0.0, 0.0, 0.0])
        self.assertGreater(b["transform"]["position"][0], 0.5)
        self.assertNotEqual(a["label"], b["label"])


class CommandPathTests(SpatialFixture):
    def test_every_origin_shares_one_history_with_undo_redo(self):
        object_id = self.add()
        gesture = {"kind": "gesture", "provider": "synthetic", "input": {"gesture": "one_hand_move", "frames": 30}}
        lease = self.service.begin_lease(self.session_id, object_id, "gesture")
        self.submit({"type": "object.transform", "target": {"id": object_id}, "mode": "set", "lease_id": lease["id"],
                     "transform": {"position": [0.5, 0.2, 0.0], "rotation": [0, 0, 0, 1], "scale": 1.0}}, gesture)
        self.say("make it bigger")
        self.submit({"type": "object.transform", "target": {"ref": "selected"}, "mode": "rotate", "degrees": 90})
        transform = self.state["objects"][object_id]["transform"]
        self.assertEqual(transform["position"], [0.5, 0.2, 0.0])
        self.assertEqual(transform["scale"], 1.25)
        events = self.service.session(self.session_id).history.events
        origins = [e["origin"]["kind"] for e in events if e["category"] == "transform"]
        self.assertEqual(origins, ["gesture", "language", "ui"])
        self.submit({"type": "history.undo"})
        self.submit({"type": "history.undo"})
        self.assertEqual(self.state["objects"][object_id]["transform"]["scale"], 1.0)
        self.submit({"type": "history.redo"})
        self.assertEqual(self.state["objects"][object_id]["transform"]["scale"], 1.25)
        report = self.service.verify_replay(self.session_id)
        self.assertTrue(report["verified"] and report["matches_live_state"])

    def test_lease_blocks_other_origins_and_undo_until_released(self):
        object_id = self.add()
        lease = self.service.begin_lease(self.session_id, object_id, "gesture")
        with self.assertRaises(CommandRejected) as caught:
            self.say_raw("make it bigger")
        self.assertEqual(caught.exception.code, "object_busy")
        with self.assertRaises(CommandRejected):
            self.submit({"type": "history.undo"})
        with self.assertRaises(CommandRejected):
            self.service.begin_lease(self.session_id, object_id, "gesture")
        self.assertTrue(self.service.end_lease(self.session_id, lease["id"]))
        self.say("make it bigger")
        self.assertEqual(self.state["objects"][object_id]["transform"]["scale"], 1.25)

    def say_raw(self, text):
        return self.submit({"type": "object.transform", "target": {"ref": "deictic"}, "mode": "scale", "factor": 1.25},
                           {"kind": "language", "provider": "test", "input": {"text": text}})

    def test_expired_lease_releases_object_and_rejects_stale_commit(self):
        object_id = self.add()
        lease = self.service.begin_lease(self.session_id, object_id, "gesture")
        self.clock.now += 10
        with self.assertRaises(CommandRejected) as caught:
            self.submit({"type": "object.transform", "target": {"id": object_id}, "mode": "set", "lease_id": lease["id"],
                         "transform": {"position": [1, 0, 0], "rotation": [0, 0, 0, 1], "scale": 1}})
        self.assertEqual(caught.exception.code, "lease_expired")
        self.say("make it bigger")

    def test_remove_requires_confirmation_and_is_undoable(self):
        object_id = self.add()
        result = self.submit({"type": "scene.remove", "target": {"id": object_id}})
        self.assertEqual(result["status"], "confirmation_required")
        self.assertIn(object_id, self.state["objects"])
        run(self.service.confirm(self.session_id, result["token"]))
        self.assertNotIn(object_id, self.state["objects"])
        self.assertEqual(self.state["selection"], [])
        self.submit({"type": "history.undo"})
        self.assertIn(object_id, self.state["objects"])

    def test_confirmation_refuses_when_scene_changed(self):
        first = self.add()
        result = self.submit({"type": "scene.remove", "target": {"id": first}})
        self.add()
        with self.assertRaises(CommandRejected) as caught:
            run(self.service.confirm(self.session_id, result["token"]))
        self.assertEqual(caught.exception.code, "scene_changed")
        self.assertIn(first, self.state["objects"])

    def test_invalid_requests_are_rejected_before_any_change(self):
        self.add()
        revision = self.service.session(self.session_id).history.revision
        for request in (
            {"type": "object.transform", "target": {"ref": "selected"}, "mode": "rotate"},
            {"type": "object.transform", "target": {"ref": "selected", "id": "obj-000000000000"}, "mode": "reset"},
            {"type": "object.display", "target": {"ref": "selected"}},
            {"type": "object.teleport"},
            {"type": "scene.add_asset", "fixture": "calibration", "asset_id": "x"},
        ):
            with self.assertRaises(RequestInvalid):
                self.submit(request)
        with self.assertRaises(RequestInvalid):
            self.submit({"type": "history.undo"}, {"kind": "hacker", "provider": "x"})
        self.assertEqual(self.service.session(self.session_id).history.revision, revision)

    def test_scale_clamps_and_reports_limit(self):
        self.add()
        result = self.submit({"type": "object.transform", "target": {"ref": "selected"}, "mode": "scale", "factor": 50})
        self.assertIn("Scale limited", " ".join(result["notes"]))
        with self.assertRaises(CommandRejected) as caught:
            self.submit({"type": "object.transform", "target": {"ref": "selected"}, "mode": "scale", "factor": 2})
        self.assertEqual(caught.exception.code, "scale_limit")

    def test_hand_anchor_must_be_fresh(self):
        object_id = self.add()
        self.service.presence(self.session_id, {"right_hand": {"position": [0.8, 1.1, 0.0], "confidence": 0.9}})
        self.say("move it to my right hand")
        self.assertEqual(self.state["objects"][object_id]["transform"]["position"], [0.8, 1.1, 0.0])
        self.clock.now += 5
        outcome = self.say("move it to my left hand")
        self.assertEqual(outcome["clarification"]["code"], "anchor_unavailable")

    def test_credential_like_text_is_not_persisted_in_history(self):
        self.add()
        run(self.service.interpret(self.session_id, "make it bigger password=hunter2hunter2hunter2"))
        events = self.service.session(self.session_id).history.events
        texts = [e["origin"].get("input", {}).get("text") for e in events if e["origin"]["kind"] == "language"]
        self.assertTrue(texts)
        self.assertNotIn("hunter2", str(texts))


class ReferenceTests(SpatialFixture):
    def test_spatial_comparative_and_recency_references(self):
        left = self.add(-1.0, "Left")
        right = self.add(1.0, "Right")
        self.submit({"type": "object.transform", "target": {"id": left}, "mode": "scale", "factor": 2})
        state, events = self.state, self.service.session(self.session_id).history.events
        self.assertEqual(resolve(ObjectRef(ref="leftmost"), state, events), left)
        self.assertEqual(resolve(ObjectRef(ref="rightmost"), state, events), right)
        self.assertEqual(resolve(ObjectRef(ref="largest"), state, events), left)
        self.assertEqual(resolve(ObjectRef(ref="smallest"), state, events), right)
        self.assertEqual(resolve(ObjectRef(ref="last_moved"), state, events), left)
        self.assertEqual(resolve(ObjectRef(ref="label", label="right"), state, events), right)

    def test_ambiguity_asks_instead_of_guessing(self):
        self.add(-1.0, "Twin A")
        self.add(1.0, "Twin B")
        self.submit({"type": "selection.select"})
        state = self.state
        with self.assertRaises(Clarification) as caught:
            resolve(ObjectRef(ref="largest"), state, [])
        self.assertEqual(caught.exception.code, "largest_tie")
        self.assertEqual(len(caught.exception.candidates), 2)
        with self.assertRaises(Clarification):
            resolve(ObjectRef(ref="deictic"), state, [])
        with self.assertRaises(Clarification):
            resolve(ObjectRef(ref="selected"), state, [])
        with self.assertRaises(Clarification):
            resolve(ObjectRef(ref="form"), state, [])
        outcome = self.say("make the twin bigger")
        self.assertIn("clarification", outcome)
        self.assertEqual({o["transform"]["scale"] for o in self.state["objects"].values()}, {1.0})

    def test_deictic_prefers_selection_then_last_touched(self):
        a = self.add(-1.0, "Alpha")
        b = self.add(1.0, "Beta")
        self.assertEqual(resolve(ObjectRef(ref="deictic"), self.state, []), b)  # newest add selected
        self.submit({"type": "selection.select"})
        events = self.service.session(self.session_id).history.events
        self.assertEqual(resolve(ObjectRef(ref="deictic"), self.state, events), b)
        self.submit({"type": "object.transform", "target": {"id": a}, "mode": "translate", "delta": [0, 0.1, 0]})
        events = self.service.session(self.session_id).history.events
        self.assertEqual(resolve(ObjectRef(ref="deictic"), self.state, events), a)


class LanguageTests(SpatialFixture):
    def interpret(self, text, summary=None):
        result = RuleInterpreter().interpret(text, summary or summarize(self.state))
        return (result.rule, result.requests, result.language) if result else None

    def test_product_examples_in_english(self):
        cases = {
            "Move that character to my right hand.": ("to_anchor", {"mode": "to_anchor", "anchor": "right_hand"}),
            "Make it bigger.": ("scale", {"mode": "scale", "factor": 1.25}),
            "Rotate it 180 degrees.": ("rotate", {"mode": "rotate", "degrees": 180.0}),
            "Show the rig.": ("rig", {"skeleton": True}),
            "Play the walking animation.": ("play", {"action": "play", "clip": "walk"}),
            "Hide the HUD.": ("view_hud", {"hud_visible": False}),
            "Load the latest FORM version.": ("form_version", {"version": "latest", "target": {"ref": "form"}}),
            "Put the selected character back in the center.": ("center", {"mode": "center", "target": {"ref": "selected"}}),
            "Undo that": ("undo", {"type": "history.undo"}),
            "make the one on the left twice as big": ("scale", {"factor": 2.0, "target": {"ref": "leftmost"}}),
            "rotate the one I just moved clockwise": ("rotate", {"degrees": -45.0, "target": {"ref": "last_moved"}}),
            "move it 30 cm left": ("translate", {"delta": [-0.3, 0.0, 0.0]}),
            "hide its HUD": ("form_hud", {"form_hud": False}),
            "turn off the vfx": ("vfx", {"vfx_visible": False}),
            "switch to v2": ("form_version", {"version": "V02"}),
            "inspect the larger character": ("inspect", {"target": {"ref": "largest"}}),
            "pause the animation": ("pause", {"action": "pause"}),
            "add the calibration block": ("load_fixture", {"fixture": "calibration"}),
        }
        summary = {"objects": [{"id": "obj-000000000001", "label": "Hero", "source": "form"}]}
        for text, (rule, expected) in cases.items():
            with self.subTest(text=text):
                parsed = self.interpret(text, summary)
                self.assertIsNotNone(parsed, text)
                self.assertEqual(parsed[0], rule)
                request = parsed[1][0]
                for key, value in expected.items():
                    self.assertEqual(request.get(key), value, f"{text}: {key}")
                parse_request(request)  # every rule output satisfies the public contract

    def test_load_latest_form_adds_when_no_form_character_is_present(self):
        rule, requests, _ = self.interpret("Load the latest FORM version.", {"objects": []})
        self.assertEqual((rule, requests[0]["form"]), ("form_load", {"version": "latest"}))
        rule, requests, _ = self.interpret("add another FORM character", {"objects": [{"id": "obj-000000000001", "label": "Hero", "source": "form"}]})
        self.assertEqual(rule, "form_load")

    def test_product_examples_in_turkish(self):
        cases = {
            "Onu sağ elime getir": ("to_anchor", "tr"),
            "Büyüt": ("scale", "tr"),
            "180 derece döndür": ("rotate", "tr"),
            "İskeleti göster": ("rig", "tr"),
            "Yürüme animasyonunu oynat": ("play", "tr"),
            "HUD'ı gizle": ("view_hud", "tr"),
            "Son FORM sürümünü yükle": ("form_load", "tr"),
            "Seçili karakteri ortaya koy": ("center", "tr"),
            "Geri al": ("undo", "tr"),
            "Soldakini biraz küçült": ("scale", "tr"),
        }
        for text, (rule, language) in cases.items():
            with self.subTest(text=text):
                parsed = self.interpret(text, {"objects": []})
                self.assertIsNotNone(parsed, text)
                self.assertEqual((parsed[0], parsed[2]), (rule, language))
                parse_request(parsed[1][0])

    def test_non_scene_text_is_not_hijacked(self):
        for text in ("What's the weather in Istanbul?", "Bugün ne yapalım?", "Write me a poem", "Research GPU prices"):
            self.assertIsNone(self.interpret(text, {"objects": []}), text)

    def test_walking_animation_refused_honestly_when_clip_missing(self):
        self.add()
        outcome = self.say("Play the walking animation.")
        self.assertEqual(outcome["rejected"]["code"], "clip_not_found")
        self.assertIn("Calibration Sway", outcome["reply"])
        outcome = self.say("Yürüme animasyonunu oynat")
        self.assertIn("rejected", outcome)

    def test_model_output_is_strictly_validated(self):
        summary = {"objects": [{"id": "obj-000000000001"}]}
        good = '<think>hidden</think>{"requests":[{"type":"object.transform","target":{"id":"obj-000000000001"},"mode":"scale","factor":1.5}]}'
        self.assertEqual(parse_model_output(good, summary)[0]["factor"], 1.5)
        for bad in ('{"requests":[{"type":"object.transform","target":{"id":"obj-999999999999"},"mode":"scale","factor":1.5}]}',
                    '{"requests":[{"type":"scene.remove","target":{"ref":"selected"}}]}',
                    '{"requests":[{"type":"shell.exec","cmd":"rm -rf /"}]}',
                    'I think you should make it bigger', '{"requests": []}', None):
            self.assertEqual(parse_model_output(bad, summary), [], bad)

    def test_model_fallback_only_after_rules_and_never_with_mock(self):
        class Provider:
            name = "ollama"
            calls = 0

            async def generate(self, **_):
                Provider.calls += 1
                return '{"requests":[{"type":"view.set","vfx_visible":false}]}'

        service = SpatialLabService(Path(self.temp.name) / "model", form_library=FormLibrary(None, candidates=[]),
                                    model_provider=lambda: Provider())
        session_id = service.create_session()["session"]["id"]
        run(service.interpret(session_id, "hide the HUD"))
        self.assertEqual(Provider.calls, 0)
        outcome = run(service.interpret(session_id, "could you calm the sparkles down"))
        self.assertEqual(Provider.calls, 1)
        self.assertTrue(outcome["interpretation"]["source"].startswith("model"))
        self.assertFalse(service.session(session_id).history.state["view"]["vfx_visible"])


if __name__ == "__main__":
    unittest.main()
