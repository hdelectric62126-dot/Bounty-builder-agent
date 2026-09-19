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

    def test_cache_is_invalidated_when_tracked_evidence_changes(self):
        self.memory.remember("policy.md", "Daniel approval is required.")
        cached = self.memory.cache_answer(
            "Is approval required?", "Yes.", ["policy.md"]
        )
        self.assertEqual(cached["tracked_evidence"], 1)
        self.assertTrue(self.memory.lookup_answer("Is approval required?", threshold=0.8)["hit"])
        self.memory.remember("policy.md", "Approval policy changed.")
        stale = self.memory.lookup_answer("Is approval required?", threshold=0.8)
        self.assertFalse(stale["hit"])
        self.assertEqual(stale["stale_candidates"], 1)

    def test_search_reports_hybrid_scores_and_freshness(self):
        self.memory.remember("policy.md", "Client payment requires Daniel approval.")
        result = self.memory.search("client payment approval", 1)[0]
        self.assertIn("lexical_score", result)
        self.assertIn("semantic_score", result)
        self.assertIn("updated_at", result)

    def test_directory_ingest_skips_private_runtime_directories(self):
        root = Path(self.temp.name) / "project"
        root.mkdir()
        (root / "README.md").write_text("Bounty Builder overview", encoding="utf-8")
        (root / ".git").mkdir()
        (root / ".git" / "config").write_text("secret", encoding="utf-8")
        report = self.memory.ingest_directory(root)
        self.assertEqual(report["files"], 1)
        self.assertEqual(self.memory.status()["sources"], 1)

    def test_directory_sync_is_incremental_and_removes_deleted_files(self):
        root = Path(self.temp.name) / "project"
        root.mkdir()
        source = root / "README.md"
        source.write_text("first version", encoding="utf-8")
        first = self.memory.ingest_directory(root)
        second = self.memory.ingest_directory(root)
        self.assertEqual(first["indexed"], 1)
        self.assertEqual(second["indexed"], 0)
        self.assertEqual(second["unchanged"], 1)
        source.unlink()
        third = self.memory.ingest_directory(root)
        self.assertEqual(third["removed"], 1)
        self.assertEqual(self.memory.status()["sources"], 0)

    def test_verified_cache_updates_duplicate_question(self):
        first = self.memory.cache_answer("What passed?", "Old answer", ["old.log"])
        second = self.memory.cache_answer(" what passed? ", "New answer", ["new.log"])
        self.assertEqual(first["cache_id"], second["cache_id"])
        self.assertTrue(second["updated"])
        self.assertEqual(self.memory.status()["cached_answers"], 1)
        hit = self.memory.lookup_answer("What passed?", threshold=0.8)
        self.assertEqual(hit["answer"], "New answer")

    def test_decision_and_context_bundle(self):
        recorded = self.memory.record_decision(
            "Deployment target", "Railway remains the production target.", ["railway.json"]
        )
        self.assertEqual(recorded["status"], "active")
        bundle = self.memory.context_bundle("Where do we deploy?", limit=3)
        self.assertIn("cached_answer", bundle)
        self.assertTrue(any(item["source"].startswith("decisions/") for item in bundle["evidence"]))

    def test_decision_rejects_unknown_status(self):
        with self.assertRaises(ValueError):
            self.memory.record_decision("Target", "Railway", status="maybe")

    def test_task_ledger_reuses_active_work_and_records_completion(self):
        first = self.memory.start_task("Upgrade assistant memory", "Initial pass")
        second = self.memory.start_task("  upgrade ASSISTANT memory  ")
        self.assertEqual(first["task_id"], second["task_id"])
        self.assertTrue(second["reused"])
        completed = self.memory.update_task(
            first["task_id"], "completed", "Verified", ["140 tests", "commit:abc"]
        )
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(len(self.memory.list_tasks("active")), 0)
        self.assertEqual(self.memory.list_tasks("completed")[0]["evidence"],
                         ["140 tests", "commit:abc"])

    def test_context_includes_active_tasks(self):
        task = self.memory.start_task("Prevent repeated work")
        bundle = self.memory.context_bundle("What is active?")
        self.assertEqual(bundle["active_tasks"][0]["task_id"], task["task_id"])
        self.assertEqual(self.memory.status()["active_tasks"], 1)


if __name__ == "__main__":
    unittest.main()
