"""Cross-language contract artifacts must match the live pydantic/domain code."""

import json
import unittest

from app.spatial import contract
from app.history import ActionHistory, ActionLog
from app.spatial.domain import SpatialSceneDomain


class ContractTests(unittest.TestCase):
    def test_checked_in_artifacts_are_current(self):
        for name, content in contract.artifacts().items():
            path = contract.ROOT / name
            self.assertTrue(path.exists(), f"{name} is missing; run python -m app.spatial.contract --write")
            self.assertEqual(path.read_text(encoding="utf-8"), content,
                             f"{name} is stale; run python -m app.spatial.contract --write")

    def test_fixture_restores_and_replays_through_the_real_history_engine(self):
        fixture = json.loads((contract.ROOT / "replay-fixture.json").read_text(encoding="utf-8"))
        self.assertIn("undo", [event["kind"] for event in fixture["events"]])
        self.assertIn("redo", [event["kind"] for event in fixture["events"]])
        log = ActionLog(fixture["header"], events=fixture["events"])
        log.verify()  # hash chain over header and every event
        history = ActionHistory.restore(SpatialSceneDomain(), log)
        self.assertEqual(history.state, fixture["final_state"])
        self.assertEqual(history.digest(), fixture["final_digest"])
        self.assertTrue(history.verify_replay().verified)

if __name__ == "__main__":
    unittest.main()
