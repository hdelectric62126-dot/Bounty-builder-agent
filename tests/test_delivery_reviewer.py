import unittest
from delivery_reviewer import CheckEvidence, REQUIRED_CHECKS, review_delivery


class DeliveryReviewerTests(unittest.TestCase):
    def test_blocks_missing_or_failed_checks(self):
        decision = review_delivery(["works"], [CheckEvidence("tests", False, "pytest", "failed")], ["app.py"])
        self.assertEqual("BLOCKED", decision.status)
        self.assertIn("tests", decision.failed)
        self.assertIn("security", decision.missing)

    def test_passed_evidence_still_requires_daniel(self):
        checks = [CheckEvidence(name, True, f"run-{name}", "passed") for name in REQUIRED_CHECKS]
        decision = review_delivery(["client criterion passes"], checks, ["app.py"])
        self.assertTrue(decision.ready_for_human_review)
        self.assertEqual("AWAITING_DANIEL_APPROVAL", decision.status)
        self.assertTrue(decision.approval_required)
        self.assertFalse(decision.automatic_handoff)

    def test_unsafe_paths_do_not_count_as_work(self):
        checks = [CheckEvidence(name, True, name, "passed") for name in REQUIRED_CHECKS]
        decision = review_delivery(["works"], checks, ["../../secret"])
        self.assertIn("changed_files", decision.missing)


if __name__ == "__main__": unittest.main()
