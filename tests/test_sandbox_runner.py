import unittest
from unittest.mock import patch

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
