import unittest

from performance_learner import PerformanceConfig, PerformanceLearner


def outcome(repository="acme/widgets", language="python", income=100, cost=10):
    return {
        "url": f"https://github.com/{repository}/issues/1",
        "repository": repository,
        "language": language,
        "income": income,
        "cost": cost,
        "hours": 2,
    }


class PerformanceLearnerTests(unittest.TestCase):
    def test_measures_source_repository_and_language(self):
        learner = PerformanceLearner(PerformanceConfig(minimum_samples=3))
        report = learner.measure([outcome()] * 3)
        self.assertEqual(3, report["cohorts"]["source"]["github.com"]["samples"])
        self.assertEqual(270, report["cohorts"]["repository"]["acme/widgets"]["net_income"])
        self.assertEqual(45, report["cohorts"]["language"]["python"]["income_per_hour"])

    def test_excludes_cohorts_below_minimum_samples(self):
        learner = PerformanceLearner(PerformanceConfig(minimum_samples=3))
        report = learner.measure([outcome()] * 2)
        self.assertNotIn("acme/widgets", report["cohorts"]["repository"])
        self.assertEqual(2, report["insufficient_evidence"]["repository"]["acme/widgets"]["samples"])

    def test_proposals_are_bounded_to_five_percent(self):
        learner = PerformanceLearner(PerformanceConfig(minimum_samples=3))
        proposal = learner.propose(
            [outcome()] * 3,
            {"repository": {"acme/widgets": 1.0}},
        )
        recommendation = proposal["recommendations"]["repository"]["acme/widgets"]
        self.assertEqual(1.05, recommendation["proposed_multiplier"])
        self.assertTrue(proposal["approval_required"])
        self.assertFalse(proposal["auto_promote"])

    def test_negative_performance_reduces_weight(self):
        learner = PerformanceLearner(PerformanceConfig(minimum_samples=3))
        proposal = learner.propose([outcome(income=0, cost=20)] * 3)
        recommendation = proposal["recommendations"]["language"]["python"]
        self.assertEqual(0.95, recommendation["proposed_multiplier"])

    def test_self_promotion_always_fails_closed(self):
        learner = PerformanceLearner()
        with self.assertRaises(PermissionError):
            learner.promote({"language": {"python": 1.05}}, approved=True)

    def test_adjustment_over_five_percent_is_invalid(self):
        with self.assertRaises(ValueError):
            PerformanceLearner(PerformanceConfig(maximum_adjustment=0.051))


if __name__ == "__main__":
    unittest.main()
