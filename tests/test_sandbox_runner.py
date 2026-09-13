import unittest
from unittest.mock import patch

from coding_gym import EXERCISES
from sandbox_runner import IsolationUnavailable, SandboxRunner, validate_files


class SandboxRunnerTests(unittest.TestCase):
    def test_rejects_traversal_and_hidden_files(self):
        for path in ("../secret", "/etc/passwd", ".env", "a/.token"):
            with self.assertRaises(ValueError):
                validate_files({path: "x"})

    def test_rejects_unknown_profile(self):
        with self.assertRaises(ValueError):
            SandboxRunner().execute({"test.py": "pass"}, "shell")

    def test_fails_closed_without_kernel_isolation(self):
        runner = SandboxRunner(bubblewrap="/missing/bwrap")
        with self.assertRaises(IsolationUnavailable):
            runner.execute({"test.py": "pass"}, "python_compile")

    def test_trusted_practice_runs_without_kernel_isolation(self):
        exercise = EXERCISES[0]
        runner = SandboxRunner(bubblewrap="/missing/bwrap")
        failed = runner.execute({"solution.py": exercise.starter,
            "test_solution.py": exercise.tests}, "trusted_practice")
        passed = runner.execute({"solution.py": exercise.solution,
            "test_solution.py": exercise.tests}, "trusted_practice")
        self.assertEqual("FAILED", failed.status)
        self.assertEqual("PASSED", passed.status)
        self.assertEqual("trusted_allowlist", passed.network)

    def test_trusted_practice_rejects_any_modified_payload(self):
        exercise = EXERCISES[0]
        with self.assertRaises(ValueError):
            SandboxRunner().execute({"solution.py": exercise.solution + "# changed\n",
                "test_solution.py": exercise.tests}, "trusted_practice")

    @patch.object(SandboxRunner, "capability_check", return_value=True)
    @patch("sandbox_runner.subprocess.run")
    def test_command_disables_network_and_clears_environment(self, run, _capability):
        run.return_value.returncode = 0
        run.return_value.stdout = "ok"
        run.return_value.stderr = ""
        result = SandboxRunner().execute({"test.py": "pass"}, "python_compile")
        command = run.call_args.args[0]
        self.assertIn("--unshare-all", command)
        self.assertIn("--clearenv", command)
        self.assertEqual("PASSED", result.status)


if __name__ == "__main__": unittest.main()
