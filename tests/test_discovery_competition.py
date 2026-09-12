import unittest
from unittest.mock import patch

from discovery import GitHubDiscovery


class FakeResponse:
    def __init__(self, payload, ok=True):
        self.payload = payload
        self.ok = ok

    def json(self):
        return self.payload


class DiscoveryCompetitionTests(unittest.TestCase):
    def test_counts_assignees_and_unique_linked_pull_requests(self):
        timeline = [
            {"event": "cross-referenced", "source": {"issue": {
                "pull_request": {"url": "https://api.github.com/repos/a/b/pulls/1"}}}},
            {"event": "cross-referenced", "source": {"issue": {
                "pull_request": {"url": "https://api.github.com/repos/a/b/pulls/1"}}}},
            {"event": "commented", "source": {"issue": {
                "pull_request": {"url": "https://api.github.com/repos/a/b/pulls/2"}}}},
        ]
        with patch("discovery.requests.get", return_value=FakeResponse(timeline)):
            result = GitHubDiscovery()._competition(
                {"number": 7, "assignees": [{"login": "worker"}]}, "a/b")
        self.assertTrue(result["assigned"])
        self.assertEqual(["worker"], result["assignees"])
        self.assertEqual(1, result["linked_pull_requests"])
        self.assertTrue(result["timeline_complete"])

    def test_timeline_failure_returns_explicit_incomplete_evidence(self):
        with patch("discovery.requests.get", return_value=FakeResponse([], ok=False)):
            result = GitHubDiscovery()._competition(
                {"number": 7, "assignees": []}, "a/b")
        self.assertFalse(result["assigned"])
        self.assertEqual(0, result["linked_pull_requests"])
        self.assertFalse(result["timeline_complete"])


if __name__ == "__main__":
    unittest.main()
