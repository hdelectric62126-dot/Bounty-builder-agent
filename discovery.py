"""Public GitHub bounty discovery with provenance and license verification."""

import os
import re
from decimal import Decimal, InvalidOperation
import requests
from policy import evaluate_source, evaluate_text, license_allowed
from repository_analyst import RepositoryAnalyst
from risk_compliance_agent import OpportunityRiskInput, evaluate_risk
from solution_planner import create_solution_plan

REWARD = re.compile(r"(?:\$|USD\s*)([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.I)
MAX_VERIFIED_REWARD = Decimal("100000")


def parse_reward_claim(text: str) -> tuple[float, bool]:
    """Return a bounded reward and whether every monetary claim was plausible."""
    values = []
    try:
        values = [Decimal(value.replace(",", "")) for value in REWARD.findall(text)]
    except InvalidOperation:
        return 0.0, False
    if any(value > MAX_VERIFIED_REWARD for value in values):
        return 0.0, False
    return float(max(values, default=Decimal("0"))), True


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
        competition = self._competition(raw, repo)
        spdx = (repo_data.get("license") or {}).get("spdx_id")
        licensing = license_allowed(spdx)
        reward, reward_claim_valid = parse_reward_claim(
            f"{raw.get('title','')} {raw.get('body') or ''}")
        labels = {label["name"].lower() for label in raw.get("labels", [])}
        tests = any(word in (raw.get("body") or "").lower() for word in ("test", "pytest", "unit test"))
        analysis = RepositoryAnalyst().analyze(repository=repo_data, issue=raw).to_dict()
        clarity = analysis["issue_clarity"]["score"]
        payment_confidence = 0.7 if reward > 0 and "bounty" in labels else 0.6 if reward > 0 else 0.0
        decision = evaluate_risk(OpportunityRiskInput(
            reward=reward, success_probability=0.35, estimated_hours=8, cash_cost=0,
            license_ok=licensing.allowed, terms_ok=source.allowed,
            payment_confidence=payment_confidence,
            scope_ambiguity=max(0, 10 - round(clarity / 10)), legal_risk=1,
            assigned=competition["assigned"],
            competing_pull_requests=competition["linked_pull_requests"],
            competition_data_complete=competition["timeline_complete"],
            reward_claim_valid=reward_claim_valid,
        ))
        item = {
            "external_id": str(raw["id"]), "title": raw["title"], "url": raw["html_url"],
            "repository": repo, "reward": reward, "license": spdx or "UNKNOWN",
            "language": repo_data.get("language") or "UNKNOWN",
            "status": decision.status, "risk_score": decision.score,
            "expected_value": decision.expected_value,
            "reason": ", ".join(decision.reason_codes), "labels": sorted(labels),
            "competition": competition,
            "repository_analysis": analysis,
            "risk_compliance": decision.audit_record,
        }
        if decision.approved and analysis["feasible"]:
            item["solution_plan"] = create_solution_plan(item, {
                "requirements": analysis["issue_clarity"]["evidence"],
                "complexity": "medium", "unknowns": analysis["blockers"],
                "test_commands": ["Run the repository's documented test suite"] if tests else [],
            }).to_dict()
        return item

    def _competition(self, raw, repo):
        """Return bounded, fail-closed evidence about ownership and competing PRs."""
        assignees = raw.get("assignees") or []
        if raw.get("assignee") and not assignees:
            assignees = [raw["assignee"]]

        issue_number = raw.get("number")
        linked_prs = set()
        timeline_complete = False
        if issue_number:
            url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/timeline"
            try:
                response = requests.get(
                    url,
                    params={"per_page": 100},
                    headers={**self.headers, "Accept": "application/vnd.github+json"},
                    timeout=15,
                )
                if response.ok:
                    timeline_complete = True
                    for event in response.json():
                        source_issue = ((event.get("source") or {}).get("issue") or {})
                        pull_request = source_issue.get("pull_request") or {}
                        pr_url = pull_request.get("url") or pull_request.get("html_url")
                        if event.get("event") == "cross-referenced" and pr_url:
                            linked_prs.add(pr_url)
            except (requests.RequestException, TypeError, ValueError):
                pass

        return {
            "assigned": bool(assignees),
            "assignees": sorted({
                str(value.get("login")) for value in assignees
                if isinstance(value, dict) and value.get("login")
            }),
            "linked_pull_requests": len(linked_prs),
            "timeline_complete": timeline_complete,
        }
