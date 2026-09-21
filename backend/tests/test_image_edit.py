import unittest

from app.api.image import _comfy_execution_timings, configure_edit_workflow


class ImageEditWorkflowTests(unittest.TestCase):
    def _workflow(self):
        return {
            "41": {"inputs": {"image": "old.png"}},
            "170:151": {"inputs": {"prompt": "old"}},
            "170:168": {"inputs": {"value": False}},
            "170:162": {"inputs": {"device": "default"}},
            "170:165": {"inputs": {"value": 4}},
            "170:169": {"inputs": {"seed": 1}},
        }

    def test_fast_and_quality_select_real_workflow_branches(self):
        fast = self._workflow()
        quality = self._workflow()
        configure_edit_workflow(fast, "input.png", " edit this ", "fast")
        configure_edit_workflow(quality, "input.png", "edit this", "quality")
        self.assertTrue(fast["170:168"]["inputs"]["value"])
        self.assertFalse(quality["170:168"]["inputs"]["value"])
        self.assertEqual(fast["170:165"]["inputs"]["value"], 8)
        self.assertEqual(quality["170:165"]["inputs"]["value"], 4)
        self.assertEqual(fast["170:162"]["inputs"]["device"], "cpu")
        self.assertEqual(quality["170:162"]["inputs"]["device"], "cpu")
        self.assertEqual(fast["170:151"]["inputs"]["prompt"], "edit this")
        self.assertNotEqual(fast["170:169"]["inputs"]["seed"], 1)

    def test_comfy_history_timing_separates_queue_and_execution(self):
        history = {"status": {"messages": [
            ["execution_start", {"timestamp": 1_250.0}],
            ["execution_success", {"timestamp": 4_750.0}],
        ]}}
        self.assertEqual(
            _comfy_execution_timings(history, 1_000.0),
            {"comfy_queue": 250.0, "comfy_execute": 3_500.0},
        )


if __name__ == "__main__":
    unittest.main()
