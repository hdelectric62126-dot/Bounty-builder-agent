import tempfile
import unittest
from pathlib import Path

from learner import Learner
from policy import evaluate_source, evaluate_text, license_allowed
from risk_agent import assess


class SafetyTests(unittest.TestCase):
    def test_blocks_unsafe_work(self):
        self.assertFalse(evaluate_text("bypass authentication", "").allowed)

    def test_only_public_github(self):
        self.assertTrue(evaluate_source("https://github.com/a/b/issues/1").allowed)
        self.assertFalse(evaluate_source("https://evil.example/task").allowed)

    def test_unknown_license_blocked(self):
        self.assertFalse(license_allowed(None).allowed)

    def test_negative_expected_value_blocked(self):
        result = assess(reward=10, success_probability=.1, hours=20, cash_cost=0,
                        legal_risk=1, license_ok=True, tests_available=True)
        self.assertFalse(result.approved)

    def test_positive_bounty_allowed(self):
        result = assess(reward=500, success_probability=.5, hours=8, cash_cost=0,
                        legal_risk=1, license_ok=True, tests_available=True)
        self.assertTrue(result.approved)

    def test_legal_risk_is_hard_stop(self):
        result = assess(reward=10000, success_probability=.9, hours=1, cash_cost=0,
                        legal_risk=5, license_ok=True, tests_available=True)
        self.assertFalse(result.approved)


class LearningTests(unittest.TestCase):
    def test_learning_waits_for_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            result = Learner(str(Path(directory) / "weights.json")).propose([])
            self.assertEqual("insufficient_evidence", result["status"])

    def test_learning_is_bounded_and_approval_gated(self):
        with tempfile.TemporaryDirectory() as directory:
            agent = Learner(str(Path(directory) / "weights.json"))
            proposal = agent.propose([{"income": 10}] * 10)
            self.assertEqual("proposal_only", proposal["status"])
            self.assertLessEqual(proposal["challenger"]["success"], 1.05)
            with self.assertRaises(PermissionError):
                agent.promote(proposal["challenger"], approved=False)


if __name__ == "__main__":
    unittest.main()

