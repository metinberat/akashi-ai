import json
import tempfile
import unittest
from pathlib import Path

from app.history import (
    ActionHistory,
    ActionLog,
    CommandRejected,
    DomainResult,
    LogCorrupted,
    ReplayDivergence,
    canonical_json,
    digest,
    quantize,
)
from app.history import patch


class ShelfDomain:
    """Small deterministic domain: named items with counts plus a cursor."""

    name = "test.shelf"
    version = "shelf-1"

    def apply(self, state, command):
        kind = command["type"]
        if kind == "put":
            state["items"][command["name"]] = command["count"]
            return DomainResult(state, "items", True, [command["name"]], "put")
        if kind == "take":
            if command["name"] not in state["items"]:
                raise CommandRejected("missing", "No such item.")
            del state["items"][command["name"]]
            return DomainResult(state, "items", True, [command["name"]], "take")
        if kind == "point":
            state["cursor"] = command["name"]
            return DomainResult(state, "cursor", False, [command["name"]], "point")
        raise CommandRejected("unknown", "Unknown command.")

    def reconcile(self, state):
        if state["cursor"] is not None and state["cursor"] not in state["items"]:
            state["cursor"] = None
        return state


ORIGIN = {"kind": "test"}


def fresh(directory=None):
    return ActionHistory.create(ShelfDomain(), "stream-1", {"items": {}, "cursor": None}, directory=directory)


class CanonicalTests(unittest.TestCase):
    def test_digest_is_key_order_independent_and_folds_negative_zero(self):
        self.assertEqual(digest({"a": 1, "b": [0.0]}), digest({"b": [-0.0], "a": 1}))
        self.assertEqual(canonical_json({"b": 1, "a": "ç"}), '{"a":"ç","b":1}')

    def test_non_finite_numbers_are_rejected(self):
        with self.assertRaises(ValueError):
            digest({"x": float("nan")})
        with self.assertRaises(ValueError):
            quantize(float("inf"))
        self.assertEqual(quantize(-0.0000001), 0.0)
        self.assertEqual(quantize(1.23456789), 1.234568)


class PatchTests(unittest.TestCase):
    def test_diff_apply_invert_round_trip(self):
        before = {"a": {"x": 1, "y": [1, 2]}, "gone": True}
        after = {"a": {"x": 2, "y": [1, 2, 3]}, "new": {"k": "v"}}
        changes = patch.diff(before, after)
        self.assertEqual(patch.apply(before, changes), after)
        self.assertEqual(patch.apply(after, patch.invert(changes)), before)

    def test_stale_patch_is_rejected_not_forced(self):
        changes = patch.diff({"a": 1}, {"a": 2})
        with self.assertRaises(patch.PatchConflict):
            patch.apply({"a": 5}, changes)
        with self.assertRaises(patch.PatchConflict):
            patch.apply({"a": 1}, [{"op": "add", "path": ["a"], "after": 3}])


class HistoryTests(unittest.TestCase):
    def test_undo_redo_and_redo_invalidation(self):
        history = fresh()
        history.execute({"type": "put", "name": "cup", "count": 1}, ORIGIN)
        history.execute({"type": "put", "name": "cup", "count": 2}, ORIGIN)
        history.undo(ORIGIN)
        self.assertEqual(history.state["items"], {"cup": 1})
        history.redo(ORIGIN)
        self.assertEqual(history.state["items"], {"cup": 2})
        history.undo(ORIGIN)
        history.execute({"type": "put", "name": "pen", "count": 1}, ORIGIN)
        self.assertFalse(history.can_redo())
        with self.assertRaises(CommandRejected):
            history.redo(ORIGIN)

    def test_non_undoable_events_are_recorded_but_skipped_by_undo(self):
        history = fresh()
        history.execute({"type": "put", "name": "cup", "count": 1}, ORIGIN)
        history.execute({"type": "point", "name": "cup"}, ORIGIN)
        self.assertEqual(history.revision, 2)
        undo = history.undo(ORIGIN)
        self.assertEqual(undo["undoes"], 1)
        # Reconciliation removes the dangling cursor as part of the undo event.
        self.assertEqual(history.state, {"items": {}, "cursor": None})
        self.assertIn(["cursor"], [p["path"] for p in undo["patches"]])

    def test_noop_produces_no_event_and_rejection_changes_nothing(self):
        history = fresh()
        history.execute({"type": "put", "name": "cup", "count": 1}, ORIGIN)
        self.assertIsNone(history.execute({"type": "put", "name": "cup", "count": 1}, ORIGIN))
        before = history.digest()
        with self.assertRaises(CommandRejected):
            history.execute({"type": "take", "name": "missing"}, ORIGIN)
        self.assertEqual(history.digest(), before)
        self.assertEqual(history.revision, 1)

    def test_state_at_and_replay_verification(self):
        history = fresh()
        history.execute({"type": "put", "name": "a", "count": 1}, ORIGIN)
        history.execute({"type": "put", "name": "b", "count": 2}, ORIGIN)
        history.undo(ORIGIN)
        history.redo(ORIGIN)
        history.execute({"type": "take", "name": "a"}, ORIGIN)
        self.assertEqual(history.state_at(1)["items"], {"a": 1})
        self.assertEqual(history.state_at(history.revision), history.state)
        report = history.verify_replay()
        self.assertTrue(report.verified)
        self.assertEqual((report.commands, report.undos, report.redos), (3, 1, 1))
        self.assertEqual(report.final_digest, history.digest())

    def test_replay_detects_nondeterministic_domain(self):
        history = fresh()
        history.execute({"type": "put", "name": "a", "count": 1}, ORIGIN)

        class Drifted(ShelfDomain):
            def apply(self, state, command):
                result = super().apply(state, command)
                result.state["items"][command["name"]] += 1
                return result

        history.domain = Drifted()
        with self.assertRaises(ReplayDivergence):
            history.verify_replay()


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "stream"

    def tearDown(self):
        self.temp.cleanup()

    def build(self):
        history = fresh(self.root)
        history.execute({"type": "put", "name": "a", "count": 1}, ORIGIN)
        history.execute({"type": "put", "name": "b", "count": 2}, ORIGIN)
        history.undo(ORIGIN)
        return history

    def test_restore_reproduces_state_and_stacks(self):
        original = self.build()
        restored = ActionHistory.restore(ShelfDomain(), ActionLog.open(self.root))
        self.assertEqual(restored.state, original.state)
        self.assertEqual((restored.undo_stack, restored.redo_stack), (original.undo_stack, original.redo_stack))
        restored.redo(ORIGIN)
        self.assertEqual(restored.state["items"], {"a": 1, "b": 2})

    def test_edited_event_is_detected(self):
        self.build()
        path = self.root / "events.jsonl"
        lines = path.read_text().splitlines()
        event = json.loads(lines[0])
        event["patches"][0]["after"] = 99
        lines[0] = json.dumps(event)
        path.write_text("\n".join(lines) + "\n")
        with self.assertRaises(LogCorrupted):
            ActionLog.open(self.root)

    def test_reordered_or_truncated_middle_is_detected(self):
        self.build()
        path = self.root / "events.jsonl"
        lines = path.read_text().splitlines()
        path.write_text("\n".join([lines[1], lines[0], lines[2]]) + "\n")
        with self.assertRaises(LogCorrupted):
            ActionLog.open(self.root)
        path.write_text("\n".join([lines[0], lines[2]]) + "\n")
        with self.assertRaises(LogCorrupted):
            ActionLog.open(self.root)

    def test_unacknowledged_torn_tail_is_dropped_and_reported(self):
        self.build()
        path = self.root / "events.jsonl"
        with path.open("a") as stream:
            stream.write('{"schema":"akashi.action-event/1","seq":4')
        log = ActionLog.open(self.root)
        self.assertTrue(log.torn_tail_recovered)
        self.assertEqual(len(log.events), 3)
        self.assertTrue(path.read_text().endswith("\n"))

    def test_patch_mismatch_on_restore_fails_closed(self):
        self.build()
        header = json.loads((self.root / "header.json").read_text())
        header["initial_state"]["items"] = {"a": 5}
        (self.root / "header.json").write_text(json.dumps(header))
        with self.assertRaises(LogCorrupted):
            ActionHistory.restore(ShelfDomain(), ActionLog.open(self.root))


if __name__ == "__main__":
    unittest.main()
