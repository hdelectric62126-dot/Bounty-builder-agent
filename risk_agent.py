"""Deterministic revenue/risk gate. Aggressive discovery, bounded execution."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    score: int
    expected_value: float
    reason: str


def assess(*, reward: float, success_probability: float, hours: float,
           cash_cost: float, legal_risk: int, license_ok: bool,
           tests_available: bool) -> RiskDecision:
    if not license_ok:
        return RiskDecision(False, 0, -cash_cost, "license gate failed")
    if legal_risk > 2:
        return RiskDecision(False, 0, -cash_cost, "legal risk exceeds hard limit")
    if reward <= 0:
        return RiskDecision(False, 0, -cash_cost, "no verified monetary reward")
    if cash_cost > 25:
        return RiskDecision(False, 0, -cash_cost, "cash-at-risk exceeds $25 task cap")
    probability = min(0.95, max(0.01, success_probability))
    expected_value = reward * probability - cash_cost - hours * 3.0
    score = round(min(100, max(0,
        probability * 45 + min(reward / 10, 25) + (15 if tests_available else 0)
        + max(0, 15 - hours))))
    if expected_value <= 0:
        return RiskDecision(False, score, round(expected_value, 2), "negative expected value")
    if score < 55:
        return RiskDecision(False, score, round(expected_value, 2), "risk-adjusted score below 55")
    return RiskDecision(True, score, round(expected_value, 2), "positive expected value within hard limits")

