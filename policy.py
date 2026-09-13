"""Non-negotiable safety, provenance, and adversarial-input policy."""

from dataclasses import dataclass
import re
import unicodedata
from urllib.parse import urlparse

APPROVED_LICENSES = {
    "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC",
    "MPL-2.0", "LGPL-2.1", "LGPL-3.0", "GPL-2.0", "GPL-3.0", "AGPL-3.0",
}

BLOCKED_TERMS = {
    "credential", "password", "phishing", "malware", "ransomware",
    "exploit", "zero-day", "bypass authentication", "steal", "scrape private",
}

PROMPT_INJECTION_TERMS = {
    "ignore previous instructions", "ignore all instructions",
    "reveal system prompt", "show system prompt", "developer message",
    "override safety", "disable safety", "jailbreak", "do not obey",
    "exfiltrate", "send environment variables", "print environment variables",
    "read secrets", "upload secrets",
}
MAX_TASK_TEXT = 100_000
ENCODED_PAYLOAD = re.compile(r"(?:[A-Za-z0-9+/]{200,}={0,2}|(?:\\x[0-9a-fA-F]{2}){40,})")


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str


def evaluate_text(title: str, body: str) -> PolicyDecision:
    raw = f"{title} {body}"
    if len(raw) > MAX_TASK_TEXT:
        return PolicyDecision(False, "adversarial input: task text exceeds limit")
    text = _canonicalize(raw)
    if ENCODED_PAYLOAD.search(text):
        return PolicyDecision(False, "adversarial input: opaque encoded payload")
    match = next((term for term in BLOCKED_TERMS if term in text), None)
    if match:
        return PolicyDecision(False, f"blocked safety term: {match}")
    injection = next((term for term in PROMPT_INJECTION_TERMS if term in text), None)
    if injection:
        return PolicyDecision(False, "adversarial input: instruction override attempt")
    compact = "".join(character for character in text if character.isalnum())
    compact_match = next((term for term in PROMPT_INJECTION_TERMS
                          if "".join(c for c in term if c.isalnum()) in compact), None)
    if compact_match:
        return PolicyDecision(False, "adversarial input: obfuscated instruction override")
    return PolicyDecision(True, "public software task passed safety screen")


def _canonicalize(value: str) -> str:
    """Collapse common Unicode/control-character obfuscation before inspection."""
    normalized = unicodedata.normalize("NFKC", str(value)).casefold()
    return "".join(character for character in normalized
                   if unicodedata.category(character) not in {"Cf", "Cc"})


def evaluate_source(url: str) -> PolicyDecision:
    host = (urlparse(url).hostname or "").lower()
    if host not in {"github.com", "api.github.com"}:
        return PolicyDecision(False, "source is not an approved public GitHub host")
    return PolicyDecision(True, "approved public source")


def license_allowed(spdx_id: str | None) -> PolicyDecision:
    if not spdx_id:
        return PolicyDecision(False, "repository license is missing or unknown")
    if spdx_id not in APPROVED_LICENSES:
        return PolicyDecision(False, f"license {spdx_id} is not allowlisted")
    return PolicyDecision(True, f"license {spdx_id} is allowlisted")
