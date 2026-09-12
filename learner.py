"""Bounded daily learning from measured outcomes; never edits policy or deploys itself."""

import json
from pathlib import Path

DEFAULT_WEIGHTS = {
    "reward": 1.0, "success": 1.0, "tests": 1.0,
    "hours": 1.0, "competition": 1.0,
}


class Learner:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self):
        if not self.path.exists():
            return DEFAULT_WEIGHTS.copy()
        return {**DEFAULT_WEIGHTS, **json.loads(self.path.read_text())}

    def propose(self, outcomes: list[dict]):
        current = self.load()
        if len(outcomes) < 10:
            return {"status": "insufficient_evidence", "current": current,
                    "minimum_outcomes": 10, "observed": len(outcomes)}
        successful = [o for o in outcomes if o.get("income", 0) > 0]
        success_rate = len(successful) / len(outcomes)
        challenger = current.copy()
        # Bounded changes: maximum 5% daily, never touches safety thresholds.
        direction = 1.05 if success_rate >= 0.5 else 0.95
        challenger["success"] = round(min(2.0, max(0.5, current["success"] * direction)), 4)
        challenger["competition"] = round(min(2.0, max(0.5, current["competition"] / direction)), 4)
        return {"status": "proposal_only", "current": current, "challenger": challenger,
                "success_rate": round(success_rate, 4), "approval_required": True}

    def promote(self, challenger: dict, approved: bool):
        if not approved:
            raise PermissionError("Daniel's approval is required")
        safe = {key: min(2.0, max(0.5, float(challenger[key]))) for key in DEFAULT_WEIGHTS}
        self.path.write_text(json.dumps(safe, indent=2))
        return safe

