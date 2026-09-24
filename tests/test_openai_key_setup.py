import hashlib
import os
import tempfile
import unittest
from unittest.mock import patch

import app


class OpenAIKeySetupTests(unittest.TestCase):
    def test_one_time_setup_token(self):
        token = "temporary-setup-token"
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with tempfile.TemporaryDirectory() as td:
            used = os.path.join(td, "used")
            with patch.dict(os.environ, {"OPENAI_KEY_SETUP_TOKEN_HASH": digest}, clear=False), \
                 patch.object(app, "OPENAI_KEY_SETUP_USED_FILE", used):
                self.assertTrue(app.key_setup_authorized(token))
                self.assertFalse(app.key_setup_authorized("wrong-token"))
                with open(used, "w", encoding="utf-8") as handle:
                    handle.write(digest)
                self.assertFalse(app.key_setup_authorized(token))

    def test_key_file_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            key_file = os.path.join(td, "openai_api_key")
            with open(key_file, "w", encoding="utf-8") as handle:
                handle.write("sk-test-private-key\n")
            with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False), \
                 patch.object(app, "OPENAI_KEY_FILE", key_file):
                self.assertEqual("sk-test-private-key", app.openai_api_key())


if __name__ == "__main__":
    unittest.main()
