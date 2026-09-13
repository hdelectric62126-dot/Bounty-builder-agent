import unittest

from review_consensus import review_consensus


def evidence(**overrides):
    value = {"sandbox_status": "PASSED", "attempts": [{"attempt": 1}],
             "inspection": {"passed": True, "changed_files": 1, "changed_lines": 4},
             "credentials_injected": False, "isolation": "railway_ephemeral_vm",
             "workspace_destroyed": True}
    value.update(overrides)
    return value


class ReviewConsensusTests(unittest.TestCase):
    def test_complete_evidence_is_unanimous(self):
        result = review_consensus(["works"], ["app.py"], evidence())
        self.assertTrue(result["unanimous"])
        self.assertEqual(1.0, result["confidence"])
        self.assertEqual(6, len(result["reviews"]))

    def test_one_failed_review_blocks_consensus(self):
        result = review_consensus(["works"], ["app.py"],
                                  evidence(workspace_destroyed=False))
        self.assertFalse(result["unanimous"])
        failed = [item["reviewer"] for item in result["reviews"] if not item["passed"]]
        self.assertIn("isolation", failed)

    def test_consensus_id_is_deterministic(self):
        first = review_consensus(["works"], ["app.py"], evidence())
        second = review_consensus(["works"], ["app.py"], evidence())
        self.assertEqual(first["consensus_id"], second["consensus_id"])


if __name__ == "__main__":
    unittest.main()
