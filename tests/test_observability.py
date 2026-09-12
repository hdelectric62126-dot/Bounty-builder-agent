import os
import tempfile
import unittest

from fastapi import HTTPException

import app
from store import Store


class ObservabilityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.original_store = app.store
        app.store = Store(os.path.join(self.directory.name, "test.db"))
        app.store.save_opportunity({
            "external_id": "123", "title": "Clear paid task", "url": "https://github.com/a/b/issues/1",
            "repository": "a/b", "reward": 100, "license": "MIT", "status": "APPROVED",
            "risk_score": 80, "expected_value": 25, "reason": "approved",
            "repository_analysis": {"feasible": True}, "risk_compliance": {"score": 80},
            "solution_plan": {"approval_status": "AWAITING_HUMAN_APPROVAL"},
        })

    def tearDown(self):
        app.store = self.original_store
        self.directory.cleanup()

    def test_detail_api_exposes_all_agent_records(self):
        response = app.opportunity_data(1)
        self.assertEqual(3, len(response["agent_records"]))

    def test_outcome_requires_admin_and_updates_realized_income(self):
        previous = os.environ.get("ADMIN_TOKEN")
        os.environ["ADMIN_TOKEN"] = "test-secret"
        try:
            body = {"opportunity_id": 1, "result": "paid", "income": 125,
                    "cost": 25, "hours": 2, "notes": "verified"}
            outcome = app.Outcome(**body)
            with self.assertRaises(HTTPException):
                app.record_outcome(outcome, None)
            response = app.record_outcome(outcome, "test-secret")
            self.assertEqual(100, response["stats"]["realized_income"])
            self.assertEqual("outcome_recorded", app.store.recent_audit(1)[0]["event"])
        finally:
            if previous is None:
                os.environ.pop("ADMIN_TOKEN", None)
            else:
                os.environ["ADMIN_TOKEN"] = previous


if __name__ == "__main__":
    unittest.main()
