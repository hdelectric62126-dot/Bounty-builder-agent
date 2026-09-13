"""Bounded client-code generation and isolated verification."""

from dataclasses import dataclass
from hashlib import sha256
import json

from task_readiness import LANGUAGE_ALIASES, SKILL_KEYWORDS
from code_inspector import inspect_code, sanitize_log
from review_consensus import review_consensus


MAX_FILES = 60
MAX_FILE_CHARS = 80_000
MAX_TOTAL_CHARS = 300_000
PROFILES = {"python": "python_diagnostics", "node": "node_diagnostics"}


def safe_files(files):
    if not isinstance(files, dict) or not 1 <= len(files) <= MAX_FILES:
        raise ValueError("invalid file count")
    cleaned = {}
    total = 0
    for path, content in files.items():
        parts = path.replace("\\", "/").split("/") if isinstance(path, str) else []
        if (not parts or path.startswith(("/", "~")) or
                any(not part or part in {".", ".."} or part.startswith(".") for part in parts)):
            raise ValueError("unsafe file path")
        if not isinstance(content, str) or len(content) > MAX_FILE_CHARS:
            raise ValueError("invalid file content")
        total += len(content)
        if total > MAX_TOTAL_CHARS:
            raise ValueError("project too large")
        cleaned[path] = content
    return cleaned


def client_readiness(project, acceptance_criteria, language, skill_profile):
    normalized = LANGUAGE_ALIASES.get(str(language).casefold(), "unsupported")
    text = " ".join([project, *acceptance_criteria]).casefold()
    required = sorted(skill for skill, words in SKILL_KEYWORDS.items()
                      if any(word in text for word in words))
    verified = set(skill_profile.get("verified_skills") or ())
    skill_evidence = skill_profile.get("skills") or {}
    evidence = (skill_profile.get("languages") or {}).get(normalized, {})
    gaps = [f"skill:{skill}" for skill in required
            if skill not in verified or int(skill_evidence.get(skill, {}).get("verified_passes") or 0) < 2]
    if normalized not in PROFILES:
        gaps.append("supported_language")
    elif (int(evidence.get("verified_passes") or 0) < 3 or
          float(evidence.get("average_score") or 0) < 90):
        gaps.append(f"verified_{normalized}_proficiency")
    if int(skill_profile.get("max_difficulty") or 0) < 5:
        gaps.append("advanced_difficulty_evidence")
    return {"ready": not gaps, "language": normalized, "required_skills": required,
            "gaps": list(dict.fromkeys(gaps))}


def build_schema():
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "maxLength": 2000},
            "files": {"type": "array", "maxItems": MAX_FILES, "items": {
                "type": "object",
                "properties": {"path": {"type": "string", "maxLength": 240},
                               "content": {"type": "string", "maxLength": MAX_FILE_CHARS}},
                "required": ["path", "content"], "additionalProperties": False}},
        },
        "required": ["summary", "files"],
        "additionalProperties": False,
    }


@dataclass(frozen=True)
class BuildResult:
    status: str
    summary: str
    changed_files: list[str]
    output_files: dict[str, str]
    evidence: dict
    source_digest: str
    output_digest: str
    model_response_id: str


class ClientJobBuilder:
    def __init__(self, generate, execute, max_attempts=3):
        self.generate = generate
        self.execute = execute
        self.max_attempts = max(1, min(int(max_attempts), 3))

    def build(self, job):
        source = safe_files(job["source_files"])
        preflight = inspect_code(source, source)
        if not preflight.passed:
            raise ValueError("source failed credential or security preflight")
        candidate = source
        attempts = []
        generated = {}
        execution = {}
        inspection = None
        for attempt in range(1, self.max_attempts + 1):
            generated = self.generate({
                "project": job["project"], "acceptance_criteria": job["acceptance_criteria"],
                "language": job["language"], "source_files": candidate,
                "diagnostic_feedback": attempts[-1] if attempts else None,
                "attempt": attempt, "maximum_attempts": self.max_attempts,
            })
            proposed = safe_files({item["path"]: item["content"] for item in generated["files"]})
            combined = safe_files({**candidate, **proposed})
            changed = sorted(path for path, content in combined.items()
                             if source.get(path) != content)
            if not changed:
                raise ValueError("builder produced no changes")
            inspection = inspect_code(source, combined)
            if not inspection.passed:
                raise ValueError("generated code failed deterministic security inspection")
            execution = self.execute(combined, PROFILES[job["language"]])
            attempt_evidence = {
                "attempt": attempt,
                "sandbox_status": str(execution.get("status", "UNKNOWN")).upper(),
                "exit_code": execution.get("exit_code"),
                "stdout": sanitize_log(execution.get("stdout")),
                "stderr": sanitize_log(execution.get("stderr")),
            }
            attempts.append(attempt_evidence)
            candidate = combined
            if attempt_evidence["sandbox_status"] == "PASSED":
                break
        passed = attempts[-1]["sandbox_status"] == "PASSED"
        evidence = {"sandbox_status": attempts[-1]["sandbox_status"],
            "profile": PROFILES[job["language"]], "attempts": attempts,
            "inspection": inspection.to_dict(),
            "duration_seconds": execution.get("duration_seconds"),
            "isolation": execution.get("isolation"),
            "workspace_destroyed": execution.get("workspace_destroyed"),
            "credentials_injected": execution.get("credentials_injected")}
        evidence["review_consensus"] = review_consensus(
            job["acceptance_criteria"], changed, evidence)
        return BuildResult(
            "AWAITING_DELIVERY_REVIEW" if passed else "TESTS_FAILED",
            str(generated.get("summary") or "")[:2000], changed, candidate, evidence,
            _digest(source), _digest(candidate), str(generated.get("response_id") or ""))


def _digest(files):
    return sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
