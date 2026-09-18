import os
import tempfile
import unittest

from performance_dashboard import build_performance_snapshot
from store import Store


class PerformanceDashboardTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.directory.name, "test.db"))
        self.store.save_opportunity({
            "external_id": "boost-1", "title": "Paid task", "url": "https://github.com/a/b/issues/1",
            "repository": "a/b", "reward": 100, "license": "MIT", "status": "APPROVED",
            "risk_score": 80, "expected_value": 25, "reason": "approved",
        })

    def tearDown(self):
        self.directory.cleanup()

    def test_snapshot_reports_activity_and_income(self):
        self.store.record_outcome(1, "paid", 125, 25, 2, "verified")
        snapshot = build_performance_snapshot(self.store)
        self.assertEqual(1, snapshot["opportunities"]["approved"])
        self.assertEqual(100, snapshot["outcomes"]["net_income"])
        self.assertEqual(50, snapshot["outcomes"]["net_income_per_hour"])
        self.assertEqual("outcome_recorded", snapshot["audit"]["latest_event"])
        self.assertTrue(snapshot["storage"]["persistent"])


if __name__ == "__main__":
    unittest.main()
