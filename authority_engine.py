"""Evidence-bound authority and capability certification."""

from hashlib import sha256
import json


HUMAN_ACTIONS = frozenset({
    "approve_quote", "accept_contract", "charge_payment", "public_submission",
    "merge_client_code", "final_delivery", "release_payment", "promote_learning",
})
SAFE_INTERNAL_ACTIONS = frozenset({
    "analyze", "train", "plan", "security_scan", "isolated_build", "repair",
    "test", "package_for_review",
})


def capability_certificates(profile):
    certificates = []
    for skill, evidence in sorted((profile.get("skills") or {}).items()):
        passes = int(evidence.get("verified_passes") or 0)
        score = float(evidence.get("average_score") or 0)
        difficulty = int(evidence.get("max_difficulty") or 0)
        tier = ("MASTERED" if passes >= 5 and score >= 95 and difficulty >= 5 else
                "VERIFIED" if passes >= 2 and score >= 90 and difficulty >= 4 else
                "PROVISIONAL" if passes >= 1 else "UNVERIFIED")
        payload = {"skill": skill, "tier": tier, "passes": passes,
                   "average_score": score, "max_difficulty": difficulty}
        payload["certificate_id"] = _evidence_id(payload)
        certificates.append(payload)
    return certificates


def decide_authority(action, evidence, required_skills, profile):
    if action in HUMAN_ACTIONS:
        return _decision(action, "DANIEL_APPROVAL_REQUIRED", False,
                         ["external_or_binding_action"], evidence)
    if action not in SAFE_INTERNAL_ACTIONS:
        return _decision(action, "DENIED", False, ["unknown_action"], evidence)
    if action in {"analyze", "train", "plan", "security_scan"}:
        return _decision(action, "AUTO_APPROVED_INTERNAL", True, [], evidence)
    tiers = {item["skill"]: item["tier"] for item in capability_certificates(profile)}
    missing = [skill for skill in required_skills
               if tiers.get(skill) not in {"VERIFIED", "MASTERED"}]
    reasons = [f"uncertified_skill:{skill}" for skill in missing]
    if action in {"isolated_build", "repair", "test", "package_for_review"}:
        if evidence.get("isolation") != "railway_ephemeral_vm":
            reasons.append("unverified_isolation")
        if evidence.get("credentials_injected") is not False:
            reasons.append("credential_boundary_unverified")
    if action == "package_for_review":
        if evidence.get("sandbox_status") != "PASSED":
            reasons.append("tests_not_passing")
        if not evidence.get("workspace_destroyed"):
            reasons.append("workspace_teardown_unverified")
        if not (evidence.get("inspection") or {}).get("passed"):
            reasons.append("inspection_not_passing")
        if not (evidence.get("review_consensus") or {}).get("unanimous"):
            reasons.append("review_consensus_not_unanimous")
    return _decision(action, "DENIED" if reasons else "AUTO_APPROVED_INTERNAL",
                     not reasons, reasons, evidence)


def _decision(action, status, authorized, reasons, evidence):
    payload = {"action": action, "status": status, "authorized": authorized,
               "reasons": reasons, "evidence": evidence}
    return {**payload, "decision_id": _evidence_id(payload),
            "scope": "internal_reversible" if authorized else "none"}


def _evidence_id(payload):
    return sha256(json.dumps(payload, sort_keys=True, default=str,
                             separators=(",", ":")).encode()).hexdigest()[:20]
