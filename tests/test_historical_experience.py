import unittest
from historical_experience import HistoricalExperienceCollector, extract_case


class Response:
    def raise_for_status(self): pass
    def json(self): return {"items": [RAW]}


RAW = {"id": 7, "title": "Fix API regression", "body": "Expected behavior with tests",
       "created_at": "2012-01-01T00:00:00Z", "closed_at": "2012-01-11T00:00:00Z",
       "comments": 4, "labels": [{"name": "bug"}], "state_reason": "completed",
       "repository_url": "https://api.github.com/repos/a/b",
       "html_url": "https://github.com/a/b/issues/7"}


class HistoricalExperienceTests(unittest.TestCase):
    def test_extracts_features_without_body_or_code(self):
        case = extract_case(RAW, 2012)
        self.assertEqual("bug_fix", case["category"])
        self.assertEqual(10, case["cycle_days"])
        self.assertNotIn("body", case)
        self.assertNotIn("title", case)

    def test_collector_marks_metadata_and_no_code_copy(self):
        report = HistoricalExperienceCollector(get=lambda *a, **k: Response()).collect_year(2012)
        self.assertFalse(report["code_copied"])
        self.assertEqual(1, report["sampled"])

    def test_outside_rolling_window_is_rejected(self):
        with self.assertRaises(ValueError):
            HistoricalExperienceCollector(get=lambda *a, **k: Response()).collect_year(1990)


if __name__ == "__main__": unittest.main()
