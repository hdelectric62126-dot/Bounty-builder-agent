import socket
import unittest


class IsolationSmokeTest(unittest.TestCase):
    def test_code_can_execute(self):
        self.assertEqual(4, 2 + 2)

    def test_network_is_disabled(self):
        with self.assertRaises(OSError):
            socket.create_connection(("1.1.1.1", 53), timeout=1)

    def test_no_credentials_are_injected(self):
        import os
        forbidden = {"GITHUB_TOKEN", "ADMIN_TOKEN", "SANDBOX_TOKEN",
                     "ALPACA_API_KEY", "ALPACA_SECRET_KEY"}
        self.assertFalse(forbidden.intersection(os.environ))


if __name__ == "__main__":
    unittest.main()

# Pull-request smoke verification.
