import os
import tempfile
import unittest

from bounty_executor import BountyContextLoader
from store import Store


def opportunity(external_id, status, reward=500, expected_value=50):
    return {
        "external_id": external_id,
        "title": "Fix upload attachment cache path",
        "url": f"https://github.com/example/repo/issues/{external_id}",
        "repository": "example/repo",
        "reward": reward,
        "license": "MIT",
        "status": status,
        "risk_score": 80 if status == "APPROVED" else 20,
        "expected_value": expected_value if status == "APPROVED" else 0,
        "reason": "APPROVE_WITHIN_POLICY" if status == "APPROVED" else "REJECTED",
    }


def deliberation():
    return {
        "decision_id": "test-decision",
        "recommendation": "AUTO_APPROVE_ISOLATED_BUILD",
        "confidence": 1.0,
        "passes": [],
        "unresolved": [],
        "approval_required": False,
    }


class BountyQueueExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.temp.name, "queue.db"))

    def tearDown(self):
        self.temp.cleanup()

    def test_stale_rows_cannot_be_claimed(self):
        self.store.save_opportunity(opportunity("101", "APPROVED", expected_value=100))
        self.store.save_opportunity(opportunity("102", "REJECTED"))
        approved = next(x for x in self.store.list_opportunities() if x["external_id"] == "101")
        rejected = next(x for x in self.store.list_opportunities() if x["external_id"] == "102")
        self.store.enqueue_work(approved["id"], deliberation())
        self.store.enqueue_work(rejected["id"], deliberation())

        self.assertEqual(1, self.store.expire_stale_work())
        rows = {row["opportunity_id"]: row for row in self.store.work_queue()}
        self.assertEqual("STALE_NOT_CURRENT", rows[rejected["id"]]["stage"])
        self.assertEqual("READY_FOR_ISOLATED_BUILD", rows[approved["id"]]["stage"])

        claimed = self.store.claim_ready_bounty()
        self.assertEqual(approved["id"], claimed["opportunity_id"])
        self.assertEqual("BUILDING", claimed["stage"])
        self.assertIsNone(self.store.claim_ready_bounty())

    def test_stage_transition_is_allowlisted(self):
        self.store.save_opportunity(opportunity("201", "APPROVED"))
        item = self.store.list_opportunities()[0]
        self.store.enqueue_work(item["id"], deliberation())
        claimed = self.store.claim_ready_bounty()
        self.store.set_bounty_stage(claimed["id"], "AWAITING_DANIEL_DELIVERY_REVIEW")
        row = self.store.work_queue()[0]
        self.assertEqual("AWAITING_DANIEL_DELIVERY_REVIEW", row["stage"])
        with self.assertRaises(ValueError):
            self.store.set_bounty_stage(claimed["id"], "PUBLIC_SUBMITTED")


class BountyContextLoaderTests(unittest.TestCase):
    def test_issue_number_requires_issue_url(self):
        self.assertEqual(
            98624,
            BountyContextLoader._issue_number(
                "https://github.com/Expensify/App/issues/98624"
            ),
        )
        with self.assertRaises(ValueError):
            BountyContextLoader._issue_number(
                "https://github.com/Expensify/App/pull/98624"
            )

    def test_path_selection_prioritizes_issue_relevance_and_manifests(self):
        loader = BountyContextLoader(max_files=4)
        tree = [
            {"type": "blob", "path": "package.json"},
            {"type": "blob", "path": "src/cache/attachmentUpload.ts"},
            {"type": "blob", "path": "src/unrelated/theme.ts"},
            {"type": "blob", "path": "tests/cache/attachmentUpload.test.ts"},
            {"type": "blob", "path": "node_modules/nope.js"},
        ]
        selected = loader._select_paths(
            tree, "node", "attachment upload cache fails after image upload"
        )
        self.assertIn("package.json", selected)
        self.assertIn("src/cache/attachmentUpload.ts", selected)
        self.assertNotIn("node_modules/nope.js", selected)


if __name__ == "__main__":
    unittest.main()
