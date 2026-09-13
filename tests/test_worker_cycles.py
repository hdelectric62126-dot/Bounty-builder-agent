import unittest
from unittest.mock import patch

import app


class WorkerCycleTests(unittest.TestCase):
    def test_training_yields_to_approved_paid_work(self):
        with patch.object(app.store, "stats", return_value={"approved": 1}), \
             patch.object(app, "run_practice_with_retry") as run:
            result = app.run_training_cycle()
        self.assertEqual("skipped", result["status"])
        run.assert_not_called()

    def test_training_cycle_records_adaptive_result(self):
        plan = [{"sequence": 4, "exercise_id": "x", "category": "testing",
                 "language": "python", "reason": "UNVERIFIED_SKILL"}]
        result = {"exercise_id": "x", "score": 100, "verified_pass": True}
        with patch.object(app.store, "stats", return_value={"approved": 0}), \
             patch.object(app.store, "practice_history", return_value=[]), \
             patch.object(app.store, "save_practice_run", return_value=1), \
             patch.object(app.store, "audit"), \
             patch.object(app, "plan_training", return_value=plan), \
             patch.object(app, "run_practice_with_retry", return_value=result):
            outcome = app.run_training_cycle()
        self.assertEqual({"status": "complete", "planned": 1, "saved": 1}, outcome)

    def test_history_failure_isolated_from_other_workers(self):
        with patch.object(app.historian, "collect_year", side_effect=RuntimeError("offline")), \
             patch.object(app.store, "audit"):
            result = app.run_history_cycle(2020)
        self.assertEqual("failed", result["status"])


if __name__ == "__main__":
    unittest.main()
