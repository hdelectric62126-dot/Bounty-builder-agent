"""Incremental learning from public software-work history without copying code."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Callable

import requests

from policy import evaluate_text


CATEGORIES = {
    "bug_fix": ("bug", "fix", "regression", "broken"),
    "automation": ("workflow", "automation", "script", "pipeline"),
    "integration": ("api", "integration", "webhook", "connector"),
    "organization": ("refactor", "organize", "cleanup", "architecture"),
    "documentation": ("documentation", "docs", "readme", "tutorial"),
    "testing": ("test", "coverage", "pytest", "unit test"),
    "feature": ("feature", "implement", "add support", "enhancement"),
}


def extract_case(raw: dict, sampled_year: int) -> dict | None:
    """Keep derived work signals only; never retain issue bodies or source code."""
    title = str(raw.get("title") or "")
    body = str(raw.get("body") or "")
    if not evaluate_text(title, body).allowed:
        return None
    text = f"{title} {body}".lower()
    category = next((name for name, terms in CATEGORIES.items()
                     if any(term in text for term in terms)), "other")
    created = _date(raw.get("created_at"))
    closed = _date(raw.get("closed_at"))
    cycle_days = max(0, (closed - created).days) if created and closed else None
    return {
        "external_id": str(raw.get("id") or ""),
        "sampled_year": sampled_year,
        "repository": str(raw.get("repository_url") or "").split("/repos/")[-1],
        "category": category,
        "cycle_days": cycle_days,
        "comments": max(0, int(raw.get("comments") or 0)),
        "labels": sorted(str(x.get("name") or "").lower()[:80]
                         for x in raw.get("labels", []) if isinstance(x, dict))[:20],
        "state_reason": str(raw.get("state_reason") or "unknown")[:40],
        "source_url": str(raw.get("html_url") or ""),
    }


class HistoricalExperienceCollector:
    """Sample one year at a time so a 20-year corpus grows within API limits."""

    def __init__(self, get: Callable = requests.get, token: str | None = None):
        self.get = get
        self.headers = {"Accept": "application/vnd.github+json"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def collect_year(self, year: int, max_items: int = 30) -> dict:
        current = datetime.now(timezone.utc).year
        if year < current - 19 or year > current:
            raise ValueError("year must be inside the rolling 20-year window")
        query = (f"is:issue is:closed created:{year}-01-01..{year}-12-31 "
                 "(bug OR feature OR automation OR integration OR refactor)")
        response = self.get("https://api.github.com/search/issues",
            params={"q": query, "sort": "comments", "order": "desc",
                    "per_page": max(1, min(max_items, 100))},
            headers=self.headers, timeout=20)
        response.raise_for_status()
        cases = [case for raw in response.json().get("items", [])
                 if (case := extract_case(raw, year))]
        return {"year": year, "cases": cases, "sampled": len(cases),
                "knowledge_type": "derived_public_metadata", "code_copied": False}


def _date(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
    except ValueError:
        return None
