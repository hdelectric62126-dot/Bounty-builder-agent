import unittest

from code_inspector import inspect_code, sanitize_log


class CodeInspectorTests(unittest.TestCase):
    def test_blocks_generated_secret(self):
        report = inspect_code({"app.py": "x=1"},
                              {"app.py": "token='sk-abcdefghijklmnopqrstuvwxyz1234'"})
        self.assertFalse(report.passed)
        self.assertEqual("secret_scanner", report.findings[0]["tool"])

    def test_blocks_dangerous_python_execution(self):
        report = inspect_code({"app.py": "x=1"}, {"app.py": "eval(user_input)"})
        self.assertFalse(report.passed)
        self.assertEqual("eval", report.findings[0]["detail"])

    def test_blocks_change_budget_overflow(self):
        source = {f"f{i}.txt": "old" for i in range(26)}
        output = {f"f{i}.txt": "new" for i in range(26)}
        self.assertFalse(inspect_code(source, output).passed)

    def test_redacts_and_truncates_diagnostic_logs(self):
        value = "sk-abcdefghijklmnopqrstuvwxyz1234 " + ("x" * 5000)
        cleaned = sanitize_log(value)
        self.assertNotIn("sk-", cleaned)
        self.assertTrue(cleaned.endswith("[truncated]"))


if __name__ == "__main__":
    unittest.main()
