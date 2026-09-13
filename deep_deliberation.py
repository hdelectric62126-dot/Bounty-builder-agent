"""Multi-pass decision synthesis for approved opportunities."""

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from task_readiness import evaluate_task_readiness


@dataclass(frozen=True)
class Deliberation:
    decision_id: str
    recommendation: str
    confidence: float
    passes: tuple[dict, ...]
    unresolved: tuple[str, ...]
    approval_required: bool = True

    def to_dict(self):
        return asdict(self)


def deliberate(opportunity: dict, agent_records: dict, experience: dict,
               skill_profile: dict | None = None) -> Deliberation:
    analysis = agent_records.get("repository_analysis", {})
    risk = agent_records.get("risk_compliance", {})
    plan = agent_records.get("solution_plan", {})
    unresolved = []
    passes = []

    passes.append({"pass": "requirements", "passed": analysis.get("issue_clarity", {}).get("clear", False),
        "evidence": analysis.get("issue_clarity", {})})
    passes.append({"pass": "feasibility", "passed": analysis.get("feasible", False),
        "evidence": {"score": analysis.get("feasibility_score"), "blockers": analysis.get("blockers", [])}})
    passes.append({"pass": "financial_risk", "passed": risk.get("status") == "APPROVED",
        "evidence": {"expected_value": risk.get("expected_value"), "score": risk.get("score"),
                     "reasons": risk.get("reason_codes", [])}})
    passes.append({"pass": "implementation_critique", "passed": bool(plan.get("steps")),
        "evidence": {"estimated_hours": plan.get("estimated_hours"),
                     "confidence": plan.get("confidence"), "tests": plan.get("test_checklist", [])}})
    historical_cases = int(experience.get("cases") or 0)
    passes.append({"pass": "historical_calibration", "passed": historical_cases >= 30,
        "evidence": {"historical_cases": historical_cases,
                     "average_cycle_days": experience.get("average_cycle_days")}})
    readiness = evaluate_task_readiness(
        opportunity, agent_records, skill_profile or {}).to_dict()
    passes.append({"pass": "verified_task_skills", "passed": readiness["ready"],
                   "evidence": readiness})

    for item in passes:
        if not item["passed"]:
            unresolved.append(item["pass"])
    passed = sum(item["passed"] for item in passes)
    confidence = round(passed / len(passes), 2)
    recommendation = ("AUTO_APPROVE_ISOLATED_BUILD" if passed == len(passes)
                      else "HOLD_FOR_MORE_EVIDENCE")
    canonical = json.dumps({"opportunity": opportunity.get("external_id"), "passes": passes},
                           sort_keys=True, default=str)
    return Deliberation(sha256(canonical.encode()).hexdigest()[:20], recommendation,
                        confidence, tuple(passes), tuple(unresolved),
                        approval_required=not readiness["internal_build_authorized"])
