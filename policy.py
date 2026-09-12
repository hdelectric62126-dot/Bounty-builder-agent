"""Non-negotiable safety and licensing policy."""

from dataclasses import dataclass
from urllib.parse import urlparse

APPROVED_LICENSES = {
    "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC",
    "MPL-2.0", "LGPL-2.1", "LGPL-3.0", "GPL-2.0", "GPL-3.0", "AGPL-3.0",
}

BLOCKED_TERMS = {
    "credential", "password", "phishing", "malware", "ransomware",
    "exploit", "zero-day", "bypass authentication", "steal", "scrape private",
}


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str


def evaluate_text(title: str, body: str) -> PolicyDecision:
    text = f"{title} {body}".lower()
    match = next((term for term in BLOCKED_TERMS if term in text), None)
    if match:
        return PolicyDecision(False, f"blocked safety term: {match}")
    return PolicyDecision(True, "public software task passed safety screen")


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

