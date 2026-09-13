"""Evidence-based authorization for isolated task building."""

from dataclasses import asdict, dataclass
from hashlib import sha256
import json


LANGUAGE_ALIASES = {
    "python": "python", "javascript": "node", "typescript": "node",
    "node": "node", "node.js": "node",
}
SKILL_KEYWORDS = {
    "api_reliability": ("api", "http", "pagination", "request"),
    "authentication_security": ("authentication", "authorization", "permission", "token", "session"),
    "concurrency_safety": ("concurrent", "concurrency", "race", "lock", "parallel"),
    "data_migrations": ("migration", "schema change", "backfill"),
    "database_safety": ("database", "sqlite", "sql", "query"),
    "dependency_safety": ("dependency", "package", "requirements", "lockfile"),
    "error_handling": ("error", "exception", "failure", "fallback"),
    "filesystem_security": ("file", "path", "directory", "upload"),
    "frontend_accessibility": ("frontend", "html", "form", "accessibility", "aria"),
    "job_reliability": ("job", "queue", "retry", "worker", "idempotent"),
    "input_validation": ("input", "json", "schema", "validate"),
    "observability": ("logging", "metrics", "audit", "observability", "trace"),
    "performance": ("performance", "latency", "cache", "optimize", "complexity"),
    "state_management": ("state", "transition", "workflow", "status"),
    "testing_quality": ("test", "regression", "coverage", "fixture"),
}


@dataclass(frozen=True)
class TaskReadiness:
    ready: bool
    status: str
    required_language: str
    required_skills: tuple[str, ...]
    verified_skills: tuple[str, ...]
    gaps: tuple[str, ...]
    evidence_id: str
    internal_build_authorized: bool
    external_action_authorized: bool = False

    def to_dict(self):
        return asdict(self)


def evaluate_task_readiness(opportunity: dict, records: dict,
                            skill_profile: dict) -> TaskReadiness:
    analysis = records.get("repository_analysis", {})
    plan = records.get("solution_plan", {})
    risk = records.get("risk_compliance", {})
    language_name = str(analysis.get("language", {}).get("name") or
                        opportunity.get("language") or "unknown").casefold()
    language = LANGUAGE_ALIASES.get(language_name, "unsupported")
    description = " ".join([
        str(opportunity.get("title") or ""), str(plan.get("summary") or ""),
        json.dumps(plan.get("steps") or (), default=str),
    ]).casefold()
    required = tuple(sorted(skill for skill, words in SKILL_KEYWORDS.items()
                            if any(word in description for word in words)))
    verified = tuple(sorted(skill_profile.get("verified_skills") or ()))
    gaps = []
    language_evidence = (skill_profile.get("languages") or {}).get(language, {})

    if risk.get("status") != "APPROVED":
        gaps.append("risk_approval")
    if not analysis.get("feasible") or not analysis.get("issue_clarity", {}).get("clear"):
        gaps.append("clear_feasible_requirements")
    if not plan.get("steps") or not plan.get("test_checklist"):
        gaps.append("tested_implementation_plan")
    if language == "unsupported":
        gaps.append("supported_language")
    elif (int(language_evidence.get("verified_passes") or 0) < 3 or
          float(language_evidence.get("average_score") or 0) < 90):
        gaps.append(f"verified_{language}_proficiency")
    if int(skill_profile.get("max_difficulty") or 0) < 5:
        gaps.append("advanced_difficulty_evidence")
    gaps.extend(f"skill:{skill}" for skill in required if skill not in verified)
    gaps = tuple(dict.fromkeys(gaps))
    ready = not gaps
    payload = {"opportunity": opportunity.get("external_id"), "language": language,
               "required": required, "verified": verified, "gaps": gaps}
    evidence_id = sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:20]
    return TaskReadiness(
        ready=ready,
        status="READY_FOR_ISOLATED_BUILD" if ready else "TRAINING_REQUIRED",
        required_language=language,
        required_skills=required,
        verified_skills=verified,
        gaps=gaps,
        evidence_id=evidence_id,
        internal_build_authorized=ready,
    )
