import tempfile
import unittest
from pathlib import Path

from local_assistant.cli import build_parser, execute
from local_assistant.memory import EmbeddingResult, LocalMemory


class FakeEmbedder:
    def embed(self, text):
        return EmbeddingResult([], "test")


class LocalAssistantCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.memory = LocalMemory(Path(self.temp.name) / "memory.db", FakeEmbedder())
        self.parser = build_parser()

    def tearDown(self):
        self.temp.cleanup()

    def test_shell_agent_can_ingest_and_request_context(self):
        project = Path(self.temp.name) / "project"
        project.mkdir()
        (project / "README.md").write_text("Railway deployment evidence", encoding="utf-8")
        report = execute(self.parser.parse_args(["ingest", str(project)]), self.memory)
        self.assertEqual(report["indexed"], 1)
        context = execute(self.parser.parse_args(["context", "Railway deployment"]), self.memory)
        self.assertEqual(len(context["evidence"]), 1)

    def test_shell_agent_can_record_decision(self):
        args = self.parser.parse_args([
            "decision", "Execution location", "Use the active cloud workspace",
            "--evidence", "user-direction", "--status", "active",
        ])
        result = execute(args, self.memory)
        self.assertEqual(result["status"], "active")

    def test_shell_agent_can_track_task_lifecycle(self):
        started = execute(self.parser.parse_args([
            "task-start", "Finish the upgrade", "--note", "Do not repeat work"
        ]), self.memory)
        finished = execute(self.parser.parse_args([
            "task-update", started["task_id"], "completed", "--evidence", "tests passed"
        ]), self.memory)
        self.assertEqual(finished["status"], "completed")
        tasks = execute(self.parser.parse_args(["tasks", "--status", "completed"]), self.memory)
        self.assertEqual(tasks["tasks"][0]["evidence"], ["tests passed"])


if __name__ == "__main__":
    unittest.main()
