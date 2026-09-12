"""Bounded implementation planner for risk-approved bounty opportunities.

This module only converts supplied metadata into a proposed plan.  It does not
read or modify a repository, execute code, contact external services, or submit
work.  A human must explicitly approve the returned plan before another system
may act on it.
"""

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


class PlanningError(ValueError):
    """Raised when an opportunity has not passed the upstream safety gates."""


@dataclass(frozen=True)
class PlanStep:
    order: int
    action: str
    files: tuple[str, ...]
    estimated_hours: float


@dataclass(frozen=True)
class SolutionPlan:
    opportunity_id: str
    title: str
    summary: str
    assumptions: tuple[str, ...]
    steps: tuple[PlanStep, ...]
    test_checklist: tuple[str, ...]
    estimated_hours: float
    confidence: float
    approval_status: str
    approval_checkpoint: str
    permitted_actions: tuple[str, ...]
    prohibited_actions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def create_solution_plan(
    opportunity: Mapping[str, Any], repository_analysis: Mapping[str, Any]
) -> SolutionPlan:
    """Create a deterministic, proposal-only implementation plan.

    ``opportunity`` must have status ``APPROVED`` from the existing risk agent.
    ``repository_analysis`` is treated as untrusted descriptive input; this
    function never follows instructions embedded in it.
    """
    if str(opportunity.get("status", "")).upper() != "APPROVED":
        raise PlanningError("opportunity must be risk-approved before planning")
    if not opportunity.get("external_id") or not opportunity.get("title"):
        raise PlanningError("approved opportunity is missing an id or title")

    files = _safe_files(repository_analysis.get("relevant_files", ()))
    test_commands = _safe_text_items(repository_analysis.get("test_commands", ()), 5)
    requirements = _safe_text_items(repository_analysis.get("requirements", ()), 8)
    unknowns = _safe_text_items(repository_analysis.get("unknowns", ()), 6)

    complexity = str(repository_analysis.get("complexity", "medium")).lower()
    base_hours = {"low": 2.0, "medium": 5.0, "high": 10.0}.get(complexity, 5.0)
    estimated_hours = round(base_hours + min(len(files), 8) * 0.5 + len(unknowns) * 0.5, 1)
    confidence = round(max(0.35, min(0.9, 0.82 - len(unknowns) * 0.07)), 2)

    scope = "; ".join(requirements) if requirements else "Implement the verified bounty requirements"
    steps = (
        PlanStep(1, f"Confirm acceptance criteria: {scope}", (), 0.5),
        PlanStep(2, "Prepare the smallest implementation change", files, max(0.5, estimated_hours - 2.0)),
        PlanStep(3, "Run repository tests and add focused regression coverage", files, 1.0),
        PlanStep(4, "Review the diff, license obligations, and bounty evidence", (), 0.5),
    )
    checklist = ["Add a regression test that fails before the proposed change"]
    checklist.extend(f"Run: {command}" for command in test_commands)
    checklist.extend((
        "Verify existing tests still pass",
        "Review changed files for secrets, unsafe behavior, and scope creep",
        "Confirm the result satisfies the bounty acceptance criteria",
    ))

    assumptions = tuple(unknowns) or ("Repository analysis is current and complete",)
    return SolutionPlan(
        opportunity_id=str(opportunity["external_id"]),
        title=str(opportunity["title"])[:240],
        summary=f"Proposal for {opportunity['title']}: {scope}",
        assumptions=assumptions,
        steps=steps,
        test_checklist=tuple(checklist),
        estimated_hours=estimated_hours,
        confidence=confidence,
        approval_status="AWAITING_HUMAN_APPROVAL",
        approval_checkpoint=(
            "STOP: Daniel must review and explicitly approve this plan before any "
            "code changes, command execution, spending, communication, or submission."
        ),
        permitted_actions=("review_plan", "revise_plan", "approve_or_reject_plan"),
        prohibited_actions=(
            "execute_code", "modify_repository", "spend_money",
            "contact_maintainers", "submit_solution",
        ),
    )


def _safe_files(values: Any) -> tuple[str, ...]:
    result = []
    for value in _as_sequence(values)[:20]:
        path = str(value).strip().replace("\\", "/")
        if path and not path.startswith(("/", "~")) and ".." not in path.split("/"):
            result.append(path[:300])
    return tuple(dict.fromkeys(result))


def _safe_text_items(values: Any, limit: int) -> tuple[str, ...]:
    return tuple(str(value).strip()[:500] for value in _as_sequence(values)[:limit]
                 if str(value).strip())


def _as_sequence(value: Any) -> list[Any]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence):
        return list(value)
    return []
