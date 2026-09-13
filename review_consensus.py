"""Independent evidence reviews for client build decisions."""

from hashlib import sha256
import json


def review_consensus(acceptance_criteria, changed_files, evidence):
    attempts = evidence.get("attempts") or []
    inspection = evidence.get("inspection") or {}
    reviews = [
        {"reviewer": "requirements", "passed": bool(acceptance_criteria),
         "reason": "acceptance criteria recorded" if acceptance_criteria else "missing criteria"},
        {"reviewer": "quality", "passed": evidence.get("sandbox_status") == "PASSED",
         "reason": "isolated diagnostics passed" if evidence.get("sandbox_status") == "PASSED"
                   else "isolated diagnostics failed"},
        {"reviewer": "security", "passed": bool(inspection.get("passed")) and
            evidence.get("credentials_injected") is False,
         "reason": "inspection passed and no credentials injected"},
        {"reviewer": "isolation", "passed": evidence.get("isolation") == "railway_ephemeral_vm"
            and evidence.get("workspace_destroyed") is True,
         "reason": "ephemeral workspace verified and destroyed"},
        {"reviewer": "change_control", "passed": bool(changed_files) and
            int(inspection.get("changed_files") or 0) <= 25 and
            int(inspection.get("changed_lines") or 0) <= 3000,
         "reason": "bounded non-empty change set"},
        {"reviewer": "repair_discipline", "passed": 1 <= len(attempts) <= 3,
         "reason": f"{len(attempts)} bounded attempt(s) recorded"},
    ]
    unanimous = all(item["passed"] for item in reviews)
    payload = {"reviews": reviews, "unanimous": unanimous,
               "confidence": round(sum(item["passed"] for item in reviews) / len(reviews), 2)}
    payload["consensus_id"] = sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:20]
    return payload
