"""Audit-ready risk and compliance gate for revenue opportunities.

The module is deliberately pure and deterministic: identical inputs always produce
the same decision and ordered reason codes.  It performs hard-stop checks before
calculating a risk-adjusted expected value.
"""

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
from typing import Any


@dataclass(frozen=True)
class OpportunityRiskInput:
    reward: float
    success_probability: float
    estimated_hours: float
    cash_cost: float
    hourly_cost: float = 3.0
    license_ok: bool = False
    terms_ok: bool = False
    payment_confidence: float = 0.0
    scope_ambiguity: int = 10
    legal_risk: int = 10
    assigned: bool = False
    competing_pull_requests: int = 0
    competition_data_complete: bool = True
    reward_claim_valid: bool = True


@dataclass(frozen=True)
class ComplianceDecision:
    approved: bool
    status: str
    score: int
    expected_value: float
    reason_codes: tuple[str, ...]
    decision_id: str
    audit_record: dict[str, Any]


def evaluate_risk(
    item: OpportunityRiskInput,
    *,
    max_cash_cost: float = 25.0,
    max_hours: float = 40.0,
    min_payment_confidence: float = 0.60,
    max_scope_ambiguity: int = 6,
    max_legal_risk: int = 2,
    max_competing_pull_requests: int = 2,
    max_reward: float = 100_000.0,
    min_expected_value: float = 1.0,
    min_score: int = 55,
) -> ComplianceDecision:
    """Evaluate an opportunity, returning stable evidence suitable for an audit log."""
    inputs = asdict(item)
    limits = {
        "max_cash_cost": max_cash_cost,
        "max_hours": max_hours,
        "min_payment_confidence": min_payment_confidence,
        "max_scope_ambiguity": max_scope_ambiguity,
        "max_legal_risk": max_legal_risk,
        "max_competing_pull_requests": max_competing_pull_requests,
        "max_reward": max_reward,
        "min_expected_value": min_expected_value,
        "min_score": min_score,
    }
    reasons: list[str] = []

    # Invalid or unbounded inputs fail closed before financial scoring.
    reward_is_finite = math.isfinite(item.reward)
    reward_within_limit = reward_is_finite and item.reward <= max_reward
    if not item.reward_claim_valid:
        reasons.append("HARD_STOP_UNVERIFIED_REWARD_CLAIM")
    if not reward_is_finite:
        reasons.append("HARD_STOP_INVALID_REWARD")
    elif item.reward > max_reward:
        reasons.append("HARD_STOP_REWARD_LIMIT")
    elif item.reward <= 0:
        reasons.append("HARD_STOP_REWARD_NOT_POSITIVE")
    if not 0 <= item.success_probability <= 1:
        reasons.append("HARD_STOP_INVALID_SUCCESS_PROBABILITY")
    if item.estimated_hours < 0 or item.estimated_hours > max_hours:
        reasons.append("HARD_STOP_TIME_LIMIT")
    if item.cash_cost < 0 or item.cash_cost > max_cash_cost:
        reasons.append("HARD_STOP_CASH_LIMIT")
    if item.hourly_cost < 0:
        reasons.append("HARD_STOP_INVALID_HOURLY_COST")
    if not item.license_ok:
        reasons.append("HARD_STOP_LICENSE")
    if not item.terms_ok:
        reasons.append("HARD_STOP_TERMS")
    if not 0 <= item.payment_confidence <= 1:
        reasons.append("HARD_STOP_INVALID_PAYMENT_CONFIDENCE")
    elif item.payment_confidence < min_payment_confidence:
        reasons.append("HARD_STOP_PAYMENT_CONFIDENCE")
    if not 0 <= item.scope_ambiguity <= 10:
        reasons.append("HARD_STOP_INVALID_SCOPE_AMBIGUITY")
    elif item.scope_ambiguity > max_scope_ambiguity:
        reasons.append("HARD_STOP_SCOPE_AMBIGUITY")
    if not 0 <= item.legal_risk <= 10:
        reasons.append("HARD_STOP_INVALID_LEGAL_RISK")
    elif item.legal_risk > max_legal_risk:
        reasons.append("HARD_STOP_LEGAL_RISK")
    if item.assigned:
        reasons.append("HARD_STOP_ALREADY_ASSIGNED")
    if not item.competition_data_complete:
        reasons.append("HARD_STOP_COMPETITION_UNVERIFIED")
    if item.competing_pull_requests < 0:
        reasons.append("HARD_STOP_INVALID_COMPETING_PULL_REQUESTS")
    elif item.competing_pull_requests > max_competing_pull_requests:
        reasons.append("HARD_STOP_OVERCOMPETED")

    valid_probabilities = (
        0 <= item.success_probability <= 1
        and 0 <= item.payment_confidence <= 1
    )
    valid_reward = item.reward_claim_valid and reward_within_limit and item.reward > 0
    expected_value = (
        item.reward * item.success_probability * item.payment_confidence
        - item.cash_cost
        - item.estimated_hours * item.hourly_cost
        if valid_probabilities and valid_reward
        else -item.cash_cost - max(0, item.estimated_hours) * max(0, item.hourly_cost)
    )
    expected_value = round(expected_value, 2)

    if not reasons:
        scope_clarity = 1 - item.scope_ambiguity / 10
        legal_safety = 1 - item.legal_risk / 10
        return_on_effort = min(1.0, max(0.0, expected_value / max(item.reward, 1)))
        score = round(100 * (
            0.30 * item.success_probability
            + 0.25 * item.payment_confidence
            + 0.20 * scope_clarity
            + 0.15 * legal_safety
            + 0.10 * return_on_effort
        ))
        if expected_value < min_expected_value:
            reasons.append("REJECT_EXPECTED_VALUE")
        if score < min_score:
            reasons.append("REJECT_RISK_SCORE")
    else:
        score = 0

    approved = not reasons
    if approved:
        reasons.append("APPROVE_WITHIN_POLICY")
    status = "APPROVED" if approved else "REJECTED"
    canonical = json.dumps(
        {"inputs": inputs, "limits": limits, "result": {"status": status, "score": score,
         "expected_value": expected_value, "reason_codes": reasons}},
        sort_keys=True,
        separators=(",", ":"),
    )
    decision_id = sha256(canonical.encode("utf-8")).hexdigest()[:20]
    audit_record = {
        "schema_version": 1,
        "agent": "risk_compliance_agent",
        "decision_id": decision_id,
        "inputs": inputs,
        "policy_limits": limits,
        "status": status,
        "score": score,
        "expected_value": expected_value,
        "reason_codes": list(reasons),
    }
    return ComplianceDecision(
        approved, status, score, expected_value, tuple(reasons), decision_id, audit_record
    )
