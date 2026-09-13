import unittest

from task_readiness import evaluate_task_readiness


def evidence(**overrides):
    opportunity = {"external_id": "1", "title": "Fix SQLite API pagination", "language": "Python"}
    records = {
        "repository_analysis": {"feasible": True, "language": {"name": "Python"},
                                "issue_clarity": {"clear": True}},
        "risk_compliance": {"status": "APPROVED"},
        "solution_plan": {"summary": "validate API input and query database",
                          "steps": [{"action": "build"}], "test_checklist": ["tests"]},
    }
    profile = {"verified_skills": ["api_reliability", "database_safety", "input_validation"],
               "languages": {"python": {"verified_passes": 8, "average_score": 100}},
               "max_difficulty": 6}
    profile.update(overrides)
    return opportunity, records, profile


class TaskReadinessTests(unittest.TestCase):
    def test_authorizes_only_isolated_build_with_matching_evidence(self):
        result = evaluate_task_readiness(*evidence())
        self.assertTrue(result.ready)
        self.assertTrue(result.internal_build_authorized)
        self.assertFalse(result.external_action_authorized)
        self.assertEqual("READY_FOR_ISOLATED_BUILD", result.status)

    def test_missing_skill_requires_training(self):
        opportunity, records, profile = evidence(verified_skills=["input_validation"])
        result = evaluate_task_readiness(opportunity, records, profile)
        self.assertFalse(result.ready)
        self.assertIn("skill:database_safety", result.gaps)

    def test_unsupported_language_fails_closed(self):
        opportunity, records, profile = evidence()
        records["repository_analysis"]["language"]["name"] = "COBOL"
        result = evaluate_task_readiness(opportunity, records, profile)
        self.assertIn("supported_language", result.gaps)

    def test_unapproved_risk_cannot_be_overridden_by_skill(self):
        opportunity, records, profile = evidence()
        records["risk_compliance"]["status"] = "REJECTED"
        result = evaluate_task_readiness(opportunity, records, profile)
        self.assertIn("risk_approval", result.gaps)


if __name__ == "__main__":
    unittest.main()
