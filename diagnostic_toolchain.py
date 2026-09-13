"""Bounded, evidence-producing diagnostics for isolated client workspaces."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Callable


Execute = Callable[[dict[str, str], str], dict]
Repair = Callable[[dict[str, str], str, int], dict[str, str] | None]


@dataclass(frozen=True)
class DiagnosticPolicy:
    max_attempts: int = 3
    max_files: int = 150
    max_total_bytes: int = 300 * 1024

    def __post_init__(self):
        if not 1 <= self.max_attempts <= 3:
            raise ValueError("max_attempts must be between 1 and 3")


def detect_language(files: dict[str, str]) -> str:
    names = set(files)
    if "package.json" in names or any(name.endswith((".js", ".mjs", ".cjs", ".ts")) for name in names):
        return "node"
    if any(name.endswith(".py") for name in names):
        return "python"
    return "unknown"


def classify_failure(result: dict) -> str:
    status = str(result.get("status", "UNKNOWN")).upper()
    if status == "PASSED":
        return "passed"
    text = f"{result.get('stdout', '')}\n{result.get('stderr', '')}\n{result.get('detail', '')}".lower()
    if status == "TIMEOUT" or "timed out" in text or "timeout" in text:
        return "timeout"
    if "modulenotfound" in text or "module not found" in text or "no module named" in text:
        return "missing_dependency"
    if "syntaxerror" in text or "syntax error" in text:
        return "syntax_error"
    if "assertionerror" in text or "failed" in text or "failure" in text:
        return "test_failure"
    if status in {"ISOLATION_NOT_CONFIGURED", "UNAVAILABLE"} or "503" in text:
        return "infrastructure"
    return "execution_error"


class DiagnosticToolchain:
    """Diagnose and optionally repair a workspace, with a hard three-attempt ceiling."""

    def __init__(self, execute: Execute, policy: DiagnosticPolicy | None = None):
        self.execute = execute
        self.policy = policy or DiagnosticPolicy()

    def _validate(self, files: dict[str, str]) -> None:
        if not files or len(files) > self.policy.max_files:
            raise ValueError("invalid file count")
        size = sum(len(value.encode()) for value in files.values())
        if size > self.policy.max_total_bytes:
            raise ValueError("workspace exceeds byte limit")

    def run(self, files: dict[str, str], repair: Repair | None = None) -> dict:
        current = dict(files)
        self._validate(current)
        language = detect_language(current)
        if language == "unknown":
            return {"status": "UNSUPPORTED", "language": language, "attempts": [],
                    "classification": "unsupported_language", "verified_pass": False}
        profile = f"{language}_diagnostics"
        attempts = []
        for number in range(1, self.policy.max_attempts + 1):
            result = self.execute(current, profile)
            classification = classify_failure(result)
            attempts.append({
                "number": number,
                "status": str(result.get("status", "UNKNOWN")).upper(),
                "classification": classification,
                "exit_code": result.get("exit_code"),
                "duration_seconds": result.get("duration_seconds"),
                "isolation": result.get("isolation", "unknown"),
                "network": result.get("network", "unknown"),
            })
            if classification == "passed":
                break
            if not repair or classification in {"timeout", "infrastructure", "missing_dependency"}:
                break
            repaired = repair(dict(current), classification, number)
            if not repaired or repaired == current:
                break
            self._validate(repaired)
            current = dict(repaired)

        final = attempts[-1]
        evidence = hashlib.sha256(json.dumps({"language": language, "profile": profile,
            "attempts": attempts}, sort_keys=True).encode()).hexdigest()[:20]
        return {"status": final["status"], "language": language, "profile": profile,
                "attempts": attempts, "attempt_count": len(attempts),
                "classification": final["classification"],
                "verified_pass": final["classification"] == "passed",
                "repair_limit": self.policy.max_attempts, "evidence_id": evidence,
                "network": final["network"], "isolation": final["isolation"],
                "source_retained": False}
