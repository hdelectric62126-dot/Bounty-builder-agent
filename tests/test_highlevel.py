import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException

import app
from store import Store


class HighLevelTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.original_store = app.store
        app.store = Store(os.path.join(self.directory.name, "test.db"))
        self.request_id = app.store.create_client_request(
            "Client Person", "client@example.com", "Build a documented test application.", "$500")

    def tearDown(self):
        app.store = self.original_store
        self.directory.cleanup()

    def test_sync_is_admin_gated_and_idempotent(self):
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret"}, clear=True):
            with self.assertRaises(HTTPException):
                app.sync_client_to_highlevel(self.request_id, None)
            with patch.object(app, "create_highlevel_contact", return_value="contact-1") as create:
                first = app.sync_client_to_highlevel(self.request_id, "secret")
                second = app.sync_client_to_highlevel(self.request_id, "secret")
        self.assertEqual("synced", first["status"])
        self.assertEqual("already_synced", second["status"])
        create.assert_called_once()

    def test_status_hides_secrets(self):
        env = {"STRIPE_SECRET_KEY": "sk_secret", "STRIPE_WEBHOOK_SECRET": "whsec_secret",
               "HIGHLEVEL_ACCESS_TOKEN": "high_secret", "HIGHLEVEL_LOCATION_ID": "loc"}
        with patch.dict(os.environ, env, clear=True):
            result = app.integration_status()
        self.assertEqual({"stripe": True, "stripe_webhook": True, "highlevel": True,
                          "openai_coding": False, "client_job_builder": False}, result)
        self.assertNotIn("secret", repr(result))


if __name__ == "__main__":
    unittest.main()
