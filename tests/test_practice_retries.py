import unittest
from unittest.mock import patch

import requests

import app


class PracticeRetryTests(unittest.TestCase):
    def test_retries_transient_capacity_failure(self):
        response = requests.Response()
        response.status_code = 503
        failure = requests.HTTPError(response=response)
        with patch.object(app.coding_gym, "run", side_effect=[failure, {"verified_pass": True}]) as run:
            result = app.run_practice_with_retry(7, pause=lambda _seconds: None)
        self.assertTrue(result["verified_pass"])
        self.assertEqual(2, run.call_count)

    def test_does_not_retry_permanent_client_error(self):
        response = requests.Response()
        response.status_code = 400
        failure = requests.HTTPError(response=response)
        with patch.object(app.coding_gym, "run", side_effect=failure) as run:
            with self.assertRaises(requests.HTTPError):
                app.run_practice_with_retry(7, pause=lambda _seconds: None)
        self.assertEqual(1, run.call_count)

    def test_stops_after_bounded_attempts(self):
        failure = requests.ConnectionError("offline")
        with patch.object(app.coding_gym, "run", side_effect=failure) as run:
            with self.assertRaises(requests.ConnectionError):
                app.run_practice_with_retry(7, attempts=3, pause=lambda _seconds: None)
        self.assertEqual(3, run.call_count)


if __name__ == "__main__":
    unittest.main()
