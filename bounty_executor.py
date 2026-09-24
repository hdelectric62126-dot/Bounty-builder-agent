"""Prepare fresh public GitHub bounty work for the existing isolated builder."""

from __future__ import annotations

import base64
from dataclasses import asdict
import json
from pathlib import Path
import re
from urllib.parse import quote

import requests


_STOP_WORDS = {
    "about","after","again","before","being","bounty","could","error","from","have",
    "issue","just","more","need","only","should","that","their","there","these","this",
    "using","when","with","would",
}
_LANGUAGE_EXTENSIONS = {
    "python": (".py",),
    "node": (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"),
}
_MANIFESTS = {
    "package.json", "pyproject.toml", "requirements.txt", "setup.py", "setup.cfg",
    "pytest.ini", "tox.ini", "jest.config.js", "vitest.config.js", "tsconfig.json",
}
_SKIP_SEGMENTS = {
    "node_modules", "vendor", "dist", "build", ".git", ".next", "coverage",
}


def _keywords(text: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9_]{4,}", str(text or "").casefold())
        if token not in _STOP_WORDS
    }


class BountyContextLoader:
    """Fetch a bounded, issue-relevant slice of a public GitHub repository."""

    def __init__(self, token=None, *, get=requests.get, max_files=12,
                 max_file_chars=20_000, max_total_chars=70_000):
        self.get = get
        self.max_files = max(1, min(int(max_files), 40))
        self.max_file_chars = max(1_000, min(int(max_file_chars), 80_000))
        self.max_total_chars = max(20_000, min(int(max_total_chars), 300_000))
        self.headers = {"Accept": "application/vnd.github+json"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def _json(self, url, **params):
        response = self.get(url, headers=self.headers, params=params or None, timeout=20)
        response.raise_for_status()
        return response.json()

    def prepare(self, opportunity: dict, records: dict) -> dict:
        repository = str(opportunity["repository"])
        issue_number = self._issue_number(opportunity["url"])
        issue = self._json(f"https://api.github.com/repos/{repository}/issues/{issue_number}")
        repo = self._json(f"https://api.github.com/repos/{repository}")
        branch = str(repo.get("default_branch") or "main")
        tree = self._json(
            f"https://api.github.com/repos/{repository}/git/trees/{quote(branch, safe='')}",
            recursive=1,
        )
        analysis = records.get("repository_analysis", {})
        language_name = str(
            (analysis.get("language") or {}).get("name")
            or opportunity.get("language")
            or ""
        ).casefold()
        language = "python" if language_name == "python" else "node" if language_name in {
            "javascript", "typescript", "node", "node.js"
        } else "unsupported"
        if language == "unsupported":
            raise ValueError("unsupported bounty language")

        issue_text = f"{issue.get('title', '')}\n{issue.get('body') or ''}"
        selected = self._select_paths(tree.get("tree") or [], language, issue_text)
        files = self._fetch_files(repository, branch, selected)
        if not files:
            raise ValueError("no bounded repository context could be fetched")

        plan = records.get("solution_plan", {})
        criteria = [str(issue.get("title") or opportunity.get("title") or "Complete bounty")]
        body = str(issue.get("body") or "").strip()
        if body:
            criteria.append(body[:12_000])
        criteria.extend(str(x)[:1_500] for x in (plan.get("test_checklist") or [])[:6])

        return {
            "project": f"{opportunity.get('title','')}\n\n{body[:16_000]}",
            "acceptance_criteria": criteria[:10],
            "language": language,
            "source_files": files,
            "repository": repository,
            "issue_number": issue_number,
            "source_url": opportunity["url"],
        }

    @staticmethod
    def _issue_number(url: str) -> int:
        match = re.search(r"/issues/(\d+)(?:$|[?#])", str(url))
        if not match:
            raise ValueError("invalid GitHub issue URL")
        return int(match.group(1))

    def _select_paths(self, tree, language, issue_text):
        extensions = _LANGUAGE_EXTENSIONS[language]
        words = _keywords(issue_text)
        ranked = []
        for entry in tree:
            if entry.get("type") != "blob":
                continue
            path = str(entry.get("path") or "")
            parts = path.split("/")
            if not path or any(part in _SKIP_SEGMENTS for part in parts):
                continue
            name = parts[-1]
            lower = path.casefold()
            if name in _MANIFESTS:
                score = 100
            elif not lower.endswith(extensions):
                continue
            else:
                score = sum(8 for word in words if word in lower)
                if any(part in {"test", "tests", "__tests__", "spec", "specs"} for part in parts):
                    score += 5
                if len(parts) <= 3:
                    score += 2
            ranked.append((score, len(path), path))
        ranked.sort(key=lambda row: (-row[0], row[1], row[2]))
        return [row[2] for row in ranked[: self.max_files]]

    def _fetch_files(self, repository, branch, paths):
        files = {}
        total = 0
        for path in paths:
            payload = self._json(
                f"https://api.github.com/repos/{repository}/contents/{quote(path, safe='/')}",
                ref=branch,
            )
            if payload.get("type") != "file":
                continue
            size = int(payload.get("size") or 0)
            if size <= 0 or size > self.max_file_chars:
                continue
            encoded = payload.get("content")
            if not encoded:
                continue
            try:
                content = base64.b64decode(encoded).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                continue
            if len(content) > self.max_file_chars or total + len(content) > self.max_total_chars:
                continue
            files[path] = content
            total += len(content)
        return files


def save_build_artifact(directory, queue_id: int, opportunity: dict, prepared: dict, result):
    """Persist a private build package on the Railway volume for later human review."""
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "queue_id": queue_id,
        "opportunity": {
            "id": opportunity.get("id"),
            "external_id": opportunity.get("external_id"),
            "title": opportunity.get("title"),
            "repository": opportunity.get("repository"),
            "url": opportunity.get("url"),
            "reward": opportunity.get("reward"),
            "expected_value": opportunity.get("expected_value"),
        },
        "prepared": {
            "repository": prepared["repository"],
            "issue_number": prepared["issue_number"],
            "language": prepared["language"],
            "source_files": sorted(prepared["source_files"]),
        },
        "result": asdict(result),
    }
    final = target_dir / f"bounty-{queue_id}.json"
    temp = final.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(final)
    return str(final)
