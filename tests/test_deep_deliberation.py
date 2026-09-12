import unittest
from deep_deliberation import deliberate


class DeepDeliberationTests(unittest.TestCase):
    def test_all_five_passes_required_for_queue(self):
        records = {"repository_analysis": {"feasible": True, "feasibility_score": 90,
                    "blockers": [], "issue_clarity": {"clear": True}},
                   "risk_compliance": {"status": "APPROVED", "score": 70,
                    "expected_value": 50, "reason_codes": ["APPROVE_WITHIN_POLICY"]},
                   "solution_plan": {"steps": [{"action": "build"}], "estimated_hours": 4,
                    "confidence": .8, "test_checklist": ["tests"]}}
        result = deliberate({"external_id": "1"}, records,
                            {"cases": 30, "average_cycle_days": 4})
        self.assertEqual("QUEUE_FOR_DANIEL_APPROVAL", result.recommendation)
        self.assertEqual(1.0, result.confidence)
        self.assertEqual(5, len(result.passes))

    def test_missing_evidence_holds_job(self):
        result = deliberate({"external_id": "1"}, {}, {"cases": 0})
        self.assertEqual("HOLD_FOR_MORE_EVIDENCE", result.recommendation)
        self.assertGreater(len(result.unresolved), 0)


if __name__ == "__main__": unittest.main()
