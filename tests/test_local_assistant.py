import tempfile
import unittest
from pathlib import Path

from local_assistant.memory import EmbeddingResult, LocalMemory


class FakeEmbedder:
    def embed(self, text):
        words = text.casefold()
        return EmbeddingResult([float("payment" in words), float("sandbox" in words), 1.0], "fake")


class LocalAssistantTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.memory = LocalMemory(Path(self.temp.name) / "memory.db", FakeEmbedder())

    def tearDown(self):
        self.temp.cleanup()

    def test_remember_and_semantic_recall(self):
        self.memory.remember("policy.md", "Client payment requires Daniel approval and signed webhook evidence.")
        self.memory.remember("sandbox.md", "Run untrusted code in the isolated sandbox.")
        results = self.memory.search("How is payment approved?", 1)
        self.assertEqual(results[0]["source"], "policy.md")

    def test_cache_hit_and_miss(self):
        self.memory.cache_answer("How does payment approval work?", "Daniel approves it.", ["policy.md"])
        hit = self.memory.lookup_answer("Explain payment approval", threshold=0.8)
        self.assertTrue(hit["hit"])
        self.assertEqual(hit["evidence"], ["policy.md"])
        self.assertFalse(self.memory.lookup_answer("sandbox network rules", threshold=0.9)["hit"])

    def test_directory_ingest_skips_private_runtime_directories(self):
        root = Path(self.temp.name) / "project"
        root.mkdir()
        (root / "README.md").write_text("Bounty Builder overview", encoding="utf-8")
        (root / ".git").mkdir()
        (root / ".git" / "config").write_text("secret", encoding="utf-8")
        report = self.memory.ingest_directory(root)
        self.assertEqual(report["files"], 1)
        self.assertEqual(self.memory.status()["sources"], 1)


if __name__ == "__main__":
    unittest.main()
