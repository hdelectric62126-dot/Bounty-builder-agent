"""Advisory repository feasibility analysis for discovered bounty work.

This agent never approves execution, changes policy, or performs repository writes.
Its output is evidence for the existing deterministic risk and human-approval gates.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import re
from typing import Any, Mapping, Sequence

from policy import license_allowed


TEST_MARKERS = (
    "test", "tests", "spec", "specs", "pytest.ini", "tox.ini",
    "jest.config.js", "vitest.config.js", ".github/workflows",
)
CLARITY_MARKERS = (
    "acceptance criteria", "expected behavior", "expected result",
    "steps to reproduce", "definition of done", "requirements",
)


@dataclass(frozen=True)
class RepositoryFeasibility:
    license: dict[str, Any]
    language: dict[str, Any]
    activity: dict[str, Any]
    tests: dict[str, Any]
    issue_clarity: dict[str, Any]
    feasibility_score: int
    feasible: bool
    blockers: list[str]
    advisory_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RepositoryAnalyst:
    """Produce deterministic feasibility evidence without authorizing work."""

    def __init__(self, *, supported_languages: Sequence[str] | None = None,
                 stale_after_days: int = 365):
        self.supported_languages = {
            value.casefold() for value in (supported_languages or ()) if value
        }
        self.stale_after_days = max(1, stale_after_days)

    def analyze(self, *, repository: Mapping[str, Any], issue: Mapping[str, Any],
                paths: Sequence[str] = (), now: datetime | None = None
                ) -> RepositoryFeasibility:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        spdx = ((repository.get("license") or {}).get("spdx_id")
                if isinstance(repository.get("license"), Mapping) else None)
        license_decision = license_allowed(spdx)
        language = str(repository.get("language") or "UNKNOWN")
        language_supported = (not self.supported_languages or
                              language.casefold() in self.supported_languages)

        pushed_at = _parse_github_time(repository.get("pushed_at"))
        age_days = (now - pushed_at).days if pushed_at else None
        active = age_days is not None and age_days <= self.stale_after_days

        normalized_paths = [str(path).casefold().strip("/") for path in paths]
        test_evidence = sorted({path for path in normalized_paths
                                if _is_test_path(path)})
        tests_present = bool(test_evidence)

        title = str(issue.get("title") or "").strip()
        body = str(issue.get("body") or "").strip()
        clarity_score, clarity_evidence = _issue_clarity(title, body)
        clear = clarity_score >= 60

        blockers = []
        if not license_decision.allowed:
            blockers.append("license_not_allowed")
        if not language_supported:
            blockers.append("unsupported_language")
        if not active:
            blockers.append("inactive_or_unknown_activity")
        if not clear:
            blockers.append("issue_requirements_unclear")

        score = round(
            (30 if license_decision.allowed else 0)
            + (20 if language_supported else 0)
            + (20 if active else 0)
            + (15 if tests_present else 0)
            + clarity_score * 0.15
        )
        return RepositoryFeasibility(
            license={"spdx_id": spdx or "UNKNOWN", "allowed": license_decision.allowed,
                     "reason": license_decision.reason},
            language={"name": language, "supported": language_supported},
            activity={"pushed_at": pushed_at.isoformat() if pushed_at else None,
                      "age_days": age_days, "active": active,
                      "stale_after_days": self.stale_after_days},
            tests={"present": tests_present, "evidence": test_evidence[:10]},
            issue_clarity={"score": clarity_score, "clear": clear,
                           "evidence": clarity_evidence},
            feasibility_score=max(0, min(100, score)),
            feasible=not blockers,
            blockers=blockers,
        )


def _parse_github_time(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _is_test_path(path: str) -> bool:
    segments = set(path.split("/"))
    return (bool(segments.intersection({"test", "tests", "spec", "specs"})) or
            any(path.endswith(marker) for marker in TEST_MARKERS[4:]))


def _issue_clarity(title: str, body: str) -> tuple[int, list[str]]:
    evidence = []
    score = 0
    if len(title) >= 12:
        score += 20
        evidence.append("descriptive_title")
    if len(body) >= 80:
        score += 25
        evidence.append("substantive_body")
    lowered = body.casefold()
    markers = [marker for marker in CLARITY_MARKERS if marker in lowered]
    if markers:
        score += 30
        evidence.append("explicit_requirements")
    if re.search(r"(?:^|\n)\s*(?:[-*]|\d+[.)])\s+\S+", body):
        score += 15
        evidence.append("structured_tasks")
    if re.search(r"`[^`]+`|```", body):
        score += 10
        evidence.append("technical_example")
    return min(100, score), evidence
