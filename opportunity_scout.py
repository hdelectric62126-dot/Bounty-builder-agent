"""Broader, bounded opportunity discovery with deterministic deduplication.

The scout deliberately delegates every candidate to ``GitHubDiscovery.evaluate`` so
the existing source, content, licensing, and risk policies remain authoritative.
It only improves how public GitHub issues are collected and consolidated.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Callable, Iterable

import requests

from discovery import GitHubDiscovery


DEFAULT_QUERIES = (
    "is:issue is:open label:bounty",
    'is:issue is:open label:"help wanted" bounty',
    'is:issue is:open in:title,body (reward OR bounty)',
)


@dataclass(frozen=True)
class ScoutReport:
    opportunities: list[dict]
    fetched: int
    duplicates: int
    rejected: int
    query_errors: int


def opportunity_key(item: dict) -> str:
    """Return a stable key across overlapping queries and minor URL variations."""
    external_id = str(item.get("external_id") or item.get("id") or "").strip()
    if external_id:
        return f"github:{external_id}"

    url = str(item.get("url") or item.get("html_url") or "").split("?", 1)[0]
    url = url.rstrip("/").lower()
    if url:
        return f"url:{url}"

    repository = re.sub(r"\s+", "", str(item.get("repository") or "").lower())
    title = re.sub(r"[^a-z0-9]+", " ", str(item.get("title") or "").lower()).strip()
    digest = hashlib.sha256(f"{repository}\0{title}".encode()).hexdigest()[:24]
    return f"fallback:{digest}"


def deduplicate(items: Iterable[dict]) -> tuple[list[dict], int]:
    """Deduplicate while retaining the strongest evaluated version of an item."""
    winners: dict[str, dict] = {}
    duplicates = 0
    for item in items:
        key = opportunity_key(item)
        previous = winners.get(key)
        if previous is None:
            winners[key] = item
            continue
        duplicates += 1
        candidate_rank = (
            item.get("status") == "APPROVED",
            float(item.get("risk_score") or 0),
            float(item.get("reward") or 0),
        )
        previous_rank = (
            previous.get("status") == "APPROVED",
            float(previous.get("risk_score") or 0),
            float(previous.get("reward") or 0),
        )
        if candidate_rank > previous_rank:
            winners[key] = item
    return list(winners.values()), duplicates


class OpportunityScout:
    """Collect from bounded public searches, then evaluate and consolidate."""

    def __init__(
        self,
        discovery: GitHubDiscovery | None = None,
        get: Callable = requests.get,
        queries: tuple[str, ...] = DEFAULT_QUERIES,
    ):
        self.discovery = discovery or GitHubDiscovery()
        self.get = get
        self.queries = queries

    def scan(self, max_items: int = 30) -> ScoutReport:
        if max_items <= 0:
            return ScoutReport([], 0, 0, 0, 0)
        per_query = max(1, min(100, max_items))
        evaluated: list[dict] = []
        fetched = rejected = query_errors = 0

        for query in self.queries:
            try:
                response = self.get(
                    "https://api.github.com/search/issues",
                    params={"q": query, "sort": "updated", "order": "desc", "per_page": per_query},
                    headers=self.discovery.headers,
                    timeout=20,
                )
                response.raise_for_status()
                raw_items = response.json().get("items", [])
            except (requests.RequestException, ValueError, TypeError):
                query_errors += 1
                continue

            fetched += len(raw_items)
            for raw in raw_items:
                try:
                    item = self.discovery.evaluate(raw)
                except (requests.RequestException, KeyError, TypeError, ValueError):
                    item = None
                if item is None:
                    rejected += 1
                else:
                    evaluated.append(item)

        unique, duplicates = deduplicate(evaluated)
        unique.sort(
            key=lambda item: (
                item.get("status") == "APPROVED",
                float(item.get("risk_score") or 0),
                float(item.get("reward") or 0),
            ),
            reverse=True,
        )
        return ScoutReport(unique[:max_items], fetched, duplicates, rejected, query_errors)
