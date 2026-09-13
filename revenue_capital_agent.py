"""Advisory-only revenue capital and spending allocation analysis."""

from dataclasses import dataclass, asdict
from hashlib import sha256
import json
import math


PROTECTED_CATEGORIES = frozenset({"housing", "utilities", "food", "health", "insurance", "transportation", "minimum_debt"})


@dataclass(frozen=True)
class CapitalPolicy:
    maximum_utilization_pct: float = 20.0
    minimum_expected_roi_pct: float = 15.0
    maximum_payback_days: int = 90
    minimum_cash_reserve_cents: int = 50000


def evaluate_capital(snapshot, opportunities, policy=CapitalPolicy()):
    """Return a deterministic plan without moving money or applying for credit."""
    _validate_snapshot(snapshot)
    spending = [_spend_item(item) for item in snapshot.get("monthly_spending", [])]
    protected = sum(item["amount_cents"] for item in spending if item["protected"])
    revenue_spend = sum(item["amount_cents"] for item in spending if item["revenue_linked"])
    redirectable = [item for item in spending if not item["protected"] and not item["revenue_linked"]]
    redirectable_total = sum(item["amount_cents"] for item in redirectable)

    limit_cents = int(snapshot.get("total_credit_limit_cents", 0))
    balance_cents = int(snapshot.get("total_credit_balance_cents", 0))
    utilization = (balance_cents / limit_cents * 100) if limit_cents else 0
    safe_ceiling = int(limit_cents * policy.maximum_utilization_pct / 100)
    credit_capacity = max(0, safe_ceiling - balance_cents)
    cash_cents = int(snapshot.get("available_cash_cents", 0))
    cash_capacity = max(0, cash_cents - policy.minimum_cash_reserve_cents)

    ranked = [_opportunity(item, credit_capacity, cash_capacity, policy) for item in opportunities]
    ranked.sort(key=lambda item: (item["decision"] == "QUALIFIED", item["expected_profit_cents"],
                                  item["expected_roi_pct"]), reverse=True)
    plan = {
        "mode": "ADVISORY_ONLY",
        "automatic_borrowing": False,
        "automatic_spending": False,
        "protected_monthly_spending_cents": protected,
        "revenue_linked_monthly_spending_cents": revenue_spend,
        "redirectable_monthly_spending_cents": redirectable_total,
        "redirectable_items": redirectable,
        "credit": {
            "limit_cents": limit_cents,
            "balance_cents": balance_cents,
            "utilization_pct": round(utilization, 2),
            "policy_ceiling_pct": policy.maximum_utilization_pct,
            "qualified_capacity_cents": credit_capacity,
            "available_credit_is_income": False,
        },
        "cash_above_reserve_cents": cash_capacity,
        "opportunities": ranked,
        "rules": asdict(policy),
        "approval_required_for": ["borrow", "charge", "transfer", "open_account", "close_account"],
    }
    plan["analysis_id"] = sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()[:20]
    return plan


def _spend_item(item):
    amount = _bounded_cents(item.get("amount_cents"), "spending amount")
    category = str(item.get("category") or "other").strip().lower()[:50]
    revenue = bool(item.get("revenue_linked", False))
    return {"label": str(item.get("label") or category).strip()[:100], "category": category,
            "amount_cents": amount, "protected": category in PROTECTED_CATEGORIES,
            "revenue_linked": revenue, "recommendation":
            "PROTECT" if category in PROTECTED_CATEGORIES else
            "MEASURE_RETURN" if revenue else "REVIEW_OR_REDIRECT"}


def _opportunity(item, credit_capacity, cash_capacity, policy):
    name = str(item.get("name") or "unnamed")[:120]
    cost = _bounded_cents(item.get("cost_cents"), "opportunity cost")
    gross = _bounded_cents(item.get("gross_revenue_cents"), "gross revenue")
    finance = _bounded_cents(item.get("finance_cost_cents", 0), "finance cost")
    probability = float(item.get("success_probability", 0))
    days = int(item.get("payback_days", 0))
    if not math.isfinite(probability) or not 0 <= probability <= 1:
        raise ValueError("success_probability must be between 0 and 1")
    if not 1 <= days <= 3650:
        raise ValueError("payback_days must be between 1 and 3650")
    expected_revenue = round(gross * probability)
    expected_profit = expected_revenue - cost - finance
    roi = expected_profit / cost * 100 if cost else 0
    funding = "CASH" if cost <= cash_capacity else "CREDIT" if cost <= credit_capacity else "UNFUNDED"
    reasons = []
    if expected_profit <= 0: reasons.append("NON_POSITIVE_EXPECTED_PROFIT")
    if roi < policy.minimum_expected_roi_pct: reasons.append("ROI_BELOW_MINIMUM")
    if days > policy.maximum_payback_days: reasons.append("PAYBACK_TOO_SLOW")
    if funding == "UNFUNDED": reasons.append("OUTSIDE_SAFE_CAPITAL")
    if not item.get("evidence", "").strip(): reasons.append("MISSING_REVENUE_EVIDENCE")
    return {"name": name, "cost_cents": cost, "expected_revenue_cents": expected_revenue,
            "expected_profit_cents": expected_profit, "expected_roi_pct": round(roi, 2),
            "payback_days": days, "funding_source": funding,
            "decision": "QUALIFIED" if not reasons else "REJECTED", "reasons": reasons,
            "evidence": str(item.get("evidence") or "")[:500]}


def _validate_snapshot(snapshot):
    for key in ("available_cash_cents", "total_credit_limit_cents", "total_credit_balance_cents"):
        _bounded_cents(snapshot.get(key, 0), key)
    if int(snapshot.get("total_credit_balance_cents", 0)) > int(snapshot.get("total_credit_limit_cents", 0)):
        raise ValueError("credit balance cannot exceed credit limit")


def _bounded_cents(value, label):
    if type(value) is not int or not 0 <= value <= 100_000_000:
        raise ValueError(f"{label} must be integer cents within bounds")
    return value
