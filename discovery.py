"""Public GitHub bounty discovery with provenance and license verification."""

import os
import re
import requests
from policy import evaluate_source, evaluate_text, license_allowed
from risk_agent import assess

REWARD = re.compile(r"(?:\$|USD\s*)([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.I)


class GitHubDiscovery:
    def __init__(self):
        self.headers = {"Accept": "application/vnd.github+json"}
        if os.getenv("GITHUB_TOKEN"):
            self.headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"

    def scan(self, max_items=30):
        query = 'is:issue is:open (label:bounty OR label:"help wanted")'
        response = requests.get("https://api.github.com/search/issues",
            params={"q": query, "sort": "updated", "order": "desc", "per_page": max_items},
            headers=self.headers, timeout=20)
        response.raise_for_status()
        results = []
        for raw in response.json().get("items", []):
            item = self.evaluate(raw)
            if item:
                results.append(item)
        return results

    def evaluate(self, raw):
        source = evaluate_source(raw.get("html_url", ""))
        text = evaluate_text(raw.get("title", ""), raw.get("body") or "")
        if not source.allowed or not text.allowed:
            return None
        repo_url = raw["repository_url"]
        repo = repo_url.split("/repos/", 1)[-1]
        repo_response = requests.get(repo_url, headers=self.headers, timeout=15)
        if not repo_response.ok:
            return None
        repo_data = repo_response.json()
        spdx = (repo_data.get("license") or {}).get("spdx_id")
        licensing = license_allowed(spdx)
        money = REWARD.findall(f"{raw.get('title','')} {raw.get('body') or ''}")
        reward = max([float(value.replace(',', '')) for value in money] or [0.0])
        labels = {label["name"].lower() for label in raw.get("labels", [])}
        tests = any(word in (raw.get("body") or "").lower() for word in ("test", "pytest", "unit test"))
        decision = assess(reward=reward, success_probability=0.35, hours=8,
            cash_cost=0, legal_risk=1, license_ok=licensing.allowed, tests_available=tests)
        return {
            "external_id": str(raw["id"]), "title": raw["title"], "url": raw["html_url"],
            "repository": repo, "reward": reward, "license": spdx or "UNKNOWN",
            "status": "APPROVED" if decision.approved else "REJECTED",
            "risk_score": decision.score, "expected_value": decision.expected_value,
            "reason": decision.reason + ("" if licensing.allowed else f"; {licensing.reason}"),
            "labels": sorted(labels),
        }

