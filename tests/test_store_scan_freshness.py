import os
import tempfile
import unittest

from store import Store


def opportunity(external_id, status="APPROVED"):
    return {
        "external_id": external_id,
        "title": f"Task {external_id}",
        "url": f"https://github.com/a/b/issues/{external_id}",
        "repository": "a/b",
        "reward": 100,
        "license": "MIT",
        "status": status,
        "risk_score": 60,
        "expected_value": 10,
        "reason": "APPROVE_WITHIN_POLICY" if status == "APPROVED" else "REJECTED",
    }


class StoreScanFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.directory.name, "test.db"))

    def tearDown(self):
        self.directory.cleanup()

    def test_rejects_old_approval_missing_from_latest_complete_scan(self):
        self.store.save_opportunity(opportunity("old"))
        self.store.save_opportunity(opportunity("current"))
        changed = self.store.reject_unseen_approvals(["current"])
        rows = {row["external_id"]: row for row in self.store.list_opportunities()}
        self.assertEqual(1, changed)
        self.assertEqual("REJECTED", rows["old"]["status"])
        self.assertEqual("REJECT_NOT_IN_LATEST_COMPLETE_SCAN", rows["old"]["reason"])
        self.assertEqual("APPROVED", rows["current"]["status"])

    def test_does_not_change_existing_rejections(self):
        self.store.save_opportunity(opportunity("rejected", "REJECTED"))
        self.assertEqual(0, self.store.reject_unseen_approvals([]))
        self.assertEqual("REJECTED", self.store.list_opportunities()[0]["status"])

    def test_rejected_opportunities_do_not_inflate_expected_value(self):
        self.store.save_opportunity(opportunity("approved"))
        rejected = opportunity("spoofed", "REJECTED")
        rejected["expected_value"] = 999_999_999_999_999_999
        self.store.save_opportunity(rejected)
        self.assertEqual(10, self.store.stats()["expected_value"])


if __name__ == "__main__":
    unittest.main()
