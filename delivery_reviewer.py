"""Evidence-based client delivery gate. It reviews results; it never fabricates them."""

from dataclasses import asdict, dataclass
from hashlib import sha256
import json


REQUIRED_CHECKS = ("tests", "lint", "security", "acceptance")


@dataclass(frozen=True)
class CheckEvidence:
    name: str
    passed: bool
    command: str
    summary: str


@dataclass(frozen=True)
class DeliveryDecision:
    status: str
    ready_for_human_review: bool
    missing: tuple[str, ...]
    failed: tuple[str, ...]
    evidence_id: str
    approval_required: bool = True
    automatic_handoff: bool = False

    def to_dict(self):
        return asdict(self)


def review_delivery(acceptance_criteria: list[str], checks: list[CheckEvidence],
                    changed_files: list[str]) -> DeliveryDecision:
    criteria = [x.strip() for x in acceptance_criteria if x.strip()]
    safe_files = [x for x in changed_files if x and not x.startswith(("/", "~"))
                  and ".." not in x.replace("\\", "/").split("/")]
    by_name = {x.name.lower(): x for x in checks}
    missing = [name for name in REQUIRED_CHECKS if name not in by_name]
    failed = [name for name in REQUIRED_CHECKS
              if name in by_name and not by_name[name].passed]
    if not criteria:
        missing.append("acceptance_criteria")
    if not safe_files:
        missing.append("changed_files")
    payload = {"criteria": criteria, "checks": [asdict(x) for x in checks],
               "files": safe_files, "missing": missing, "failed": failed}
    evidence_id = sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:20]
    ready = not missing and not failed
    return DeliveryDecision("AWAITING_DANIEL_APPROVAL" if ready else "BLOCKED",
        ready, tuple(missing), tuple(failed), evidence_id)
