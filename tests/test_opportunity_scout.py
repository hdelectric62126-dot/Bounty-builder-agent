import unittest

import requests

from opportunity_scout import OpportunityScout, deduplicate, opportunity_key


class FakeResponse:
    def __init__(self, items=None, error=False):
        self.items = items or []
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise requests.HTTPError("search failed")

    def json(self):
        return {"items": self.items}


class FakeDiscovery:
    headers = {"Accept": "application/vnd.github+json"}

    def evaluate(self, raw):
        if raw.get("malformed"):
            raise KeyError("repository_url")
        if raw.get("unsafe"):
            return None
        return {
            "external_id": str(raw["id"]),
            "title": raw["title"],
            "url": raw["html_url"],
            "repository": "owner/repo",
            "reward": raw.get("reward", 0),
            "status": raw.get("status", "REJECTED"),
            "risk_score": raw.get("risk_score", 0),
        }


class OpportunityScoutTests(unittest.TestCase):
    def test_key_normalizes_url_when_id_is_missing(self):
        first = opportunity_key({"url": "https://github.com/A/B/issues/7/?ref=x"})
        second = opportunity_key({"url": "https://github.com/a/b/issues/7"})
        self.assertEqual(first, second)

    def test_deduplicate_keeps_stronger_evaluation(self):
        weak = {"external_id": "7", "status": "REJECTED", "risk_score": 10, "reward": 500}
        strong = {"external_id": "7", "status": "APPROVED", "risk_score": 50, "reward": 100}
        items, count = deduplicate([weak, strong])
        self.assertEqual(1, count)
        self.assertEqual([strong], items)

    def test_scan_combines_queries_filters_and_deduplicates(self):
        calls = iter([
            FakeResponse([
                {"id": 1, "title": "one", "html_url": "https://github.com/a/b/issues/1", "status": "APPROVED", "risk_score": 70},
                {"id": 2, "title": "unsafe", "html_url": "https://github.com/a/b/issues/2", "unsafe": True},
            ]),
            FakeResponse([
                {"id": 1, "title": "one", "html_url": "https://github.com/a/b/issues/1", "status": "APPROVED", "risk_score": 70},
                {"id": 3, "title": "three", "html_url": "https://github.com/a/b/issues/3", "risk_score": 20},
            ]),
        ])

        scout = OpportunityScout(
            discovery=FakeDiscovery(),
            get=lambda *args, **kwargs: next(calls),
            queries=("first", "second"),
        )
        report = scout.scan(max_items=10)

        self.assertEqual(["1", "3"], [item["external_id"] for item in report.opportunities])
        self.assertEqual(4, report.fetched)
        self.assertEqual(1, report.duplicates)
        self.assertEqual(1, report.rejected)

    def test_one_failed_query_does_not_abort_the_scan(self):
        calls = iter([FakeResponse(error=True), FakeResponse([])])
        scout = OpportunityScout(
            discovery=FakeDiscovery(),
            get=lambda *args, **kwargs: next(calls),
            queries=("first", "second"),
        )
        report = scout.scan()
        self.assertEqual(1, report.query_errors)
        self.assertEqual([], report.opportunities)

    def test_one_malformed_candidate_does_not_abort_the_scan(self):
        scout = OpportunityScout(
            discovery=FakeDiscovery(),
            get=lambda *args, **kwargs: FakeResponse([
                {"malformed": True},
                {"id": 4, "title": "valid", "html_url": "https://github.com/a/b/issues/4"},
            ]),
            queries=("one",),
        )
        report = scout.scan()
        self.assertEqual(1, report.rejected)
        self.assertEqual(["4"], [item["external_id"] for item in report.opportunities])


if __name__ == "__main__":
    unittest.main()
