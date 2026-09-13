"""Bounded client-code generation and isolated verification."""

from dataclasses import dataclass
from hashlib import sha256
import json

from task_readiness import LANGUAGE_ALIASES, SKILL_KEYWORDS


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
    evidence = (skill_profile.get("languages") or {}).get(normalized, {})
    gaps = [f"skill:{skill}" for skill in required if skill not in verified]
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
    def __init__(self, generate, execute):
        self.generate = generate
        self.execute = execute

    def build(self, job):
        source = safe_files(job["source_files"])
        generated = self.generate({
            "project": job["project"],
            "acceptance_criteria": job["acceptance_criteria"],
            "language": job["language"],
            "source_files": source,
        })
        proposed = safe_files({item["path"]: item["content"] for item in generated["files"]})
        changed = sorted(path for path, content in proposed.items()
                         if source.get(path) != content)
        if not changed:
            raise ValueError("builder produced no changes")
        combined = {**source, **proposed}
        combined = safe_files(combined)
        execution = self.execute(combined, PROFILES[job["language"]])
        passed = str(execution.get("status", "")).upper() == "PASSED"
        evidence = {
            "sandbox_status": str(execution.get("status", "UNKNOWN")).upper(),
            "profile": PROFILES[job["language"]],
            "exit_code": execution.get("exit_code"),
            "duration_seconds": execution.get("duration_seconds"),
            "isolation": execution.get("isolation"),
            "workspace_destroyed": execution.get("workspace_destroyed"),
            "credentials_injected": execution.get("credentials_injected"),
        }
        return BuildResult(
            "AWAITING_DELIVERY_REVIEW" if passed else "TESTS_FAILED",
            str(generated.get("summary") or "")[:2000], changed, combined, evidence,
            _digest(source), _digest(combined), str(generated.get("response_id") or ""))


def _digest(files):
    return sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
