import unittest

from client_job_builder import ClientJobBuilder, client_readiness, safe_files


class ClientJobBuilderTests(unittest.TestCase):
    def test_rejects_traversal_and_hidden_paths(self):
        for path in ("../secret", "/etc/passwd", ".env", "src/.token"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                safe_files({path: "x"})

    def test_requires_task_matched_skill(self):
        profile = {"verified_skills": [], "skills": {}, "languages": {
            "python": {"verified_passes": 10, "average_score": 100}},
            "max_difficulty": 6}
        result = client_readiness("Repair authentication token permission", ["tests pass"],
                                  "Python", profile)
        self.assertFalse(result["ready"])
        self.assertIn("skill:authentication_security", result["gaps"])

    def test_one_pass_is_provisional_not_job_authority(self):
        profile = {"verified_skills": ["testing_quality"],
                   "skills": {"testing_quality": {"verified_passes": 1,
                              "average_score": 100, "max_difficulty": 5}},
                   "languages": {"python": {"verified_passes": 10, "average_score": 100}},
                   "max_difficulty": 6}
        result = client_readiness("Fix regression", ["tests pass"], "python", profile)
        self.assertIn("skill:testing_quality", result["gaps"])

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

    def test_uses_sandbox_failure_to_drive_bounded_repair(self):
        packets = []
        def generate(packet):
            packets.append(packet)
            value = "x=2" if packet["attempt"] == 1 else "x=3"
            return {"summary": "repair", "files": [{"path": "app.py", "content": value}]}
        executions = iter((
            {"status": "FAILED", "exit_code": 1, "stderr": "assertion failed"},
            {"status": "PASSED", "exit_code": 0, "stderr": ""},
        ))
        result = ClientJobBuilder(generate, lambda _files, _profile: next(executions)).build({
            "project": "fix", "acceptance_criteria": ["test"], "language": "python",
            "source_files": {"app.py": "x=1"}})
        self.assertEqual("AWAITING_DELIVERY_REVIEW", result.status)
        self.assertEqual(2, len(packets))
        self.assertEqual("FAILED", packets[1]["diagnostic_feedback"]["sandbox_status"])
        self.assertEqual(2, len(result.evidence["attempts"]))


if __name__ == "__main__":
    unittest.main()
