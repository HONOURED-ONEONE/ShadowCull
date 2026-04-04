import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from server.tasks import TASKS
from server.grader import calculate_final_score
from shadow_cull_env.models import ShadowCullState, ShadowCullObservation

class TestNoveltyInvariants(unittest.TestCase):
    def test_all_tasks_declare_hazard_axes(self):
        """Test that each canonical task declares all 5 hazard axes, bundle name, and expected failure classes."""
        self.assertEqual(len(TASKS), 3, "There should be exactly 3 canonical tasks")
        for task_name, task_data in TASKS.items():
            self.assertIn("scenario_config", task_data, f"Task {task_name} missing scenario_config")
            config = task_data["scenario_config"]
            self.assertTrue(hasattr(config, "logic_pathology"))
            self.assertTrue(hasattr(config, "dependency_topology"))
            self.assertTrue(hasattr(config, "data_semantics"))
            self.assertTrue(hasattr(config, "operational_constraint"))
            self.assertTrue(hasattr(config, "governance_requirement"))
            self.assertTrue(hasattr(config, "hazard_bundle_name"))
            self.assertTrue(hasattr(config, "expected_failure_classes"))

    def test_zombie_api_semantics_only_in_hard_task(self):
        """Test that Zombie API semantics appear only in the hard task."""
        for task_name, task_data in TASKS.items():
            has_zombie = task_data.get("truth_type") == "stateful_zombie"
            has_hidden_mutating = len(task_data.get("hidden_mutating_endpoints", [])) > 0
            
            if "hard" in task_name.lower() or "stateful" in task_name.lower():
                self.assertTrue(has_zombie, f"Hard task {task_name} should have stateful_zombie truth type")
                self.assertTrue(has_hidden_mutating, f"Hard task {task_name} should have hidden mutating endpoints")
            else:
                self.assertFalse(has_zombie, f"Non-hard task {task_name} should NOT have stateful_zombie truth type")
                self.assertFalse(has_hidden_mutating, f"Non-hard task {task_name} should NOT have hidden mutating endpoints")

    def test_final_grader_normalized(self):
        """Test that final grader output remains normalized to [0.0, 1.0] and returns the breakdown."""
        state = ShadowCullState()
        obs = ShadowCullObservation()

        # Test base score
        score, breakdown = calculate_final_score(state, obs)
        self.assertTrue(0.0 <= score <= 1.0)
        self.assertIn("semantic_equivalence_component", breakdown)

        # Test perfect score
        state.semantic_equivalence_score = 1.0
        state.safe_shim_deployed = True
        state.budget_remaining = 8
        score, breakdown = calculate_final_score(state, obs)
        self.assertEqual(score, 1.0)
        self.assertEqual(breakdown["semantic_equivalence_component"], 0.4)
        self.assertEqual(breakdown["endpoint_handling_component"], 0.4)
        self.assertEqual(breakdown["efficiency_component"], 0.2)

        # Test cascading failure
        state.cascading_failure = True
        score, breakdown = calculate_final_score(state, obs)
        self.assertEqual(score, 0.0)
        self.assertIn("CASCADING_FAILURE (Score 0.0)", breakdown["score_caps_triggered"])

if __name__ == "__main__":
    unittest.main()
