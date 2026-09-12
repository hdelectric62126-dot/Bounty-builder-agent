import unittest
from datetime import datetime, timezone

from repository_analyst import RepositoryAnalyst


NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)


class RepositoryAnalystTests(unittest.TestCase):
    def setUp(self):
        self.agent = RepositoryAnalyst(supported_languages=("Python", "JavaScript"))
        self.issue = {
            "title": "Add retry handling to the API client",
            "body": (
                "Requirements:\n- Retry HTTP 429 responses three times.\n"
                "- Keep the existing timeout behavior.\n"
                "Expected behavior: `pytest` passes and existing callers remain compatible."
            ),
        }
        self.repository = {
            "license": {"spdx_id": "MIT"},
            "language": "Python",
            "pushed_at": "2026-09-10T12:00:00Z",
        }

    def test_produces_structured_feasibility_evidence(self):
        result = self.agent.analyze(repository=self.repository, issue=self.issue,
                                    paths=("src/client.py", "tests/test_client.py"), now=NOW)
        self.assertTrue(result.feasible)
        self.assertTrue(result.license["allowed"])
        self.assertTrue(result.language["supported"])
        self.assertTrue(result.activity["active"])
        self.assertTrue(result.tests["present"])
        self.assertTrue(result.issue_clarity["clear"])
        self.assertTrue(result.advisory_only)
        self.assertGreaterEqual(result.feasibility_score, 85)

    def test_license_is_a_hard_feasibility_blocker(self):
        repository = {**self.repository, "license": {"spdx_id": "NOASSERTION"}}
        result = self.agent.analyze(repository=repository, issue=self.issue,
                                    paths=("tests/test_client.py",), now=NOW)
        self.assertFalse(result.feasible)
        self.assertIn("license_not_allowed", result.blockers)

    def test_reports_stale_unsupported_and_unclear_repository(self):
        repository = {
            "license": {"spdx_id": "Apache-2.0"},
            "language": "COBOL",
            "pushed_at": "2020-01-01T00:00:00Z",
        }
        result = self.agent.analyze(repository=repository,
                                    issue={"title": "bug", "body": "fix it"},
                                    paths=("src/main.cbl",), now=NOW)
        self.assertFalse(result.feasible)
        self.assertEqual(
            ["unsupported_language", "inactive_or_unknown_activity",
             "issue_requirements_unclear"],
            result.blockers,
        )
        self.assertFalse(result.tests["present"])

    def test_does_not_claim_execution_approval(self):
        result = self.agent.analyze(repository=self.repository, issue=self.issue,
                                    paths=("pytest.ini",), now=NOW).to_dict()
        self.assertNotIn("approved", result)
        self.assertTrue(result["advisory_only"])


if __name__ == "__main__":
    unittest.main()
