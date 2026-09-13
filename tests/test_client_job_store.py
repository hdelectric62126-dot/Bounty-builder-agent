import os
import tempfile
import unittest

from store import Store


class ClientJobStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.directory.name, "jobs.db"))
        self.request_id = self.store.create_client_request("Ada", "ada@example.com",
            "Repair the failing Python API tests", "$100")

    def tearDown(self):
        self.directory.cleanup()

    def test_unpaid_request_cannot_enter_builder(self):
        with self.assertRaises(PermissionError):
            self.store.create_client_job(self.request_id, "python", "python_diagnostics",
                ["tests pass"], {"app.py": "x=1"}, ["testing_quality"])

    def test_paid_job_is_claimed_exactly_once(self):
        with self.store.connect() as db:
            db.execute("UPDATE client_requests SET status='PAID',payment_status='paid' WHERE id=?",
                       (self.request_id,))
        job_id = self.store.create_client_job(self.request_id, "python", "python_diagnostics",
            ["tests pass"], {"app.py": "x=1"}, ["testing_quality"])
        claimed = self.store.claim_client_job()
        self.assertEqual(job_id, claimed["id"])
        self.assertEqual("BUILDING", claimed["status"])
        self.assertIsNone(self.store.claim_client_job())


if __name__ == "__main__":
    unittest.main()
