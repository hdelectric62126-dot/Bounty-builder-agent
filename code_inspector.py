"""Deterministic inspection tools for generated client code."""

import ast
from dataclasses import dataclass, asdict
import re


SECRET_PATTERNS = (
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
)
NODE_DANGERS = (
    ("dynamic_eval", re.compile(r"\beval\s*\(")),
    ("shell_execution", re.compile(r"\b(?:exec|execSync|spawn)\s*\(")),
    ("child_process", re.compile(r"(?:node:)?child_process")),
)


@dataclass(frozen=True)
class InspectionReport:
    passed: bool
    findings: tuple[dict, ...]
    changed_files: int
    changed_lines: int

    def to_dict(self):
        return asdict(self)


def inspect_code(source_files, output_files, max_changed_files=25, max_changed_lines=3000):
    findings = []
    changed = [path for path, content in output_files.items()
               if source_files.get(path) != content]
    changed_lines = sum(_line_delta(source_files.get(path, ""), output_files[path])
                        for path in changed)
    if len(changed) > max_changed_files:
        findings.append({"tool": "change_budget", "severity": "block",
                         "detail": "too many changed files"})
    if changed_lines > max_changed_lines:
        findings.append({"tool": "change_budget", "severity": "block",
                         "detail": "too many changed lines"})
    for path, content in output_files.items():
        for name, pattern in SECRET_PATTERNS:
            if pattern.search(content):
                findings.append({"tool": "secret_scanner", "severity": "block",
                                 "file": path, "detail": name})
        if path.endswith(".py"):
            findings.extend(_inspect_python(path, content))
        elif path.endswith((".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx")):
            for name, pattern in NODE_DANGERS:
                if pattern.search(content):
                    findings.append({"tool": "static_security", "severity": "block",
                                     "file": path, "detail": name})
    return InspectionReport(not findings, tuple(findings), len(changed), changed_lines)


def sanitize_log(value, limit=4000):
    text = str(value or "")
    for _name, pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text[:limit] + ("\n[truncated]" if len(text) > limit else "")


def _inspect_python(path, content):
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return [{"tool": "syntax_scan", "severity": "block", "file": path,
                 "detail": "invalid_python"}]
    findings = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name in {"eval", "exec", "os.system", "pickle.loads", "marshal.loads"}:
                findings.append({"tool": "static_security", "severity": "block",
                                 "file": path, "line": getattr(node, "lineno", None),
                                 "detail": name})
            if name in {"subprocess.run", "subprocess.call", "subprocess.Popen"}:
                if any(keyword.arg == "shell" and isinstance(keyword.value, ast.Constant)
                       and keyword.value.value is True for keyword in node.keywords):
                    findings.append({"tool": "static_security", "severity": "block",
                                     "file": path, "line": getattr(node, "lineno", None),
                                     "detail": "subprocess_shell_true"})
    return findings


def _call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_call_name(node.value)}.{node.attr}".lstrip(".")
    return ""


def _line_delta(before, after):
    old = before.splitlines()
    new = after.splitlines()
    shared = sum(1 for left, right in zip(old, new) if left == right)
    return (len(old) - shared) + (len(new) - shared)
