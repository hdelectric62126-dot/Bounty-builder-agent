import unittest

from client_job_builder import ClientJobBuilder, client_readiness, safe_files


class ClientJobBuilderTests(unittest.TestCase):
    def test_rejects_traversal_and_hidden_paths(self):
        for path in ("../secret", "/etc/passwd", ".env", "src/.token"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                safe_files({path: "x"})

    def test_requires_task_matched_skill(self):
        profile = {"verified_skills": [], "languages": {
            "python": {"verified_passes": 10, "average_score": 100}},
            "max_difficulty": 6}
        result = client_readiness("Repair authentication token permission", ["tests pass"],
                                  "Python", profile)
        self.assertFalse(result["ready"])
        self.assertIn("skill:authentication_security", result["gaps"])

    def test_verified_build_runs_combined_files_in_fixed_profile(self):
        calls = []
        def generate(_packet):
            return {"summary": "fixed", "response_id": "resp-1",
                    "files": [{"path": "app.py", "content": "print('fixed')"}]}
        def execute(files, profile):
            calls.append((files, profile))
            return {"status": "PASSED", "exit_code": 0,
                    "isolation": "railway_ephemeral_vm", "workspace_destroyed": True,
                    "credentials_injected": False}
        result = ClientJobBuilder(generate, execute).build({
            "project": "fix it", "acceptance_criteria": ["works"],
            "language": "python", "source_files": {"app.py": "print('broken')"}})
        self.assertEqual("AWAITING_DELIVERY_REVIEW", result.status)
        self.assertEqual(["app.py"], result.changed_files)
        self.assertEqual("python_diagnostics", calls[0][1])
        self.assertTrue(result.evidence["workspace_destroyed"])

    def test_passing_model_cannot_fake_failed_sandbox(self):
        builder = ClientJobBuilder(
            lambda _packet: {"summary": "done", "files": [{"path": "app.py", "content": "x=2"}]},
            lambda _files, _profile: {"status": "FAILED", "exit_code": 1})
        result = builder.build({"project": "fix", "acceptance_criteria": ["test"],
                                "language": "python", "source_files": {"app.py": "x=1"}})
        self.assertEqual("TESTS_FAILED", result.status)


if __name__ == "__main__":
    unittest.main()
