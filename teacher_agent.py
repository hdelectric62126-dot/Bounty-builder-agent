"""Evidence-driven curriculum, remediation, and internal teacher accreditation.

This module never claims third-party accreditation.  It measures whether the local
teacher process has enough diverse, reproducible evidence to teach a domain.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json


ACCREDITATION_STANDARD = "BBA-INTERNAL-TEACHER-1"
MIN_PASSES = 3
MIN_EXAM_FORMS = 2
MIN_DIFFICULTY = 4
MIN_SCORE = 90


DOMAIN_MAP = {
    "software_foundations": {"algorithm", "correctness", "data_cleaning", "error_handling"},
    "secure_engineering": {"authentication_security", "dependency_safety",
                           "filesystem_security", "input_validation", "database_safety"},
    "reliable_services": {"api_reliability", "job_reliability", "reliability",
                          "state_management", "concurrency_safety", "observability"},
    "delivery_quality": {"testing_quality", "performance", "frontend_accessibility",
                         "data_migrations", "javascript_correctness"},
}


def exam_form(exercise_id: str, sequence: int) -> str:
    """Create a stable form identity without revealing test content."""
    generation = max(0, int(sequence)) // 23
    return sha256(f"{exercise_id}:{generation}".encode()).hexdigest()[:12]


class TeacherAgent:
    """Plans targeted instruction and reports evidence-bound qualifications."""

    def curriculum(self, exercises, history):
        by_skill = defaultdict(list)
        for result in history:
            by_skill[str(result.get("category") or "unknown")].append(result)

        lessons = []
        for exercise in exercises:
            evidence = by_skill[exercise.category]
            verified = [item for item in evidence if item.get("verified_pass")]
            forms = {exam_form(item.get("exercise_id", ""), item.get("sequence", 0))
                     for item in verified}
            failures = len(evidence) - len(verified)
            reasons = []
            if not verified:
                reasons.append("NO_VERIFIED_PASS")
            if len(verified) < MIN_PASSES:
                reasons.append("INSUFFICIENT_REPETITION")
            if len(forms) < MIN_EXAM_FORMS:
                reasons.append("INSUFFICIENT_EXAM_DIVERSITY")
            if failures:
                reasons.append("REMEDIATION_REQUIRED")
            lessons.append({
                "exercise_id": exercise.exercise_id,
                "skill": exercise.category,
                "language": exercise.language,
                "difficulty": exercise.difficulty,
                "lesson": exercise.lesson,
                "priority": 100 + failures * 10 + exercise.difficulty if reasons else exercise.difficulty,
                "reasons": reasons or ["SPACED_REVIEW"],
                "verified_passes": len(verified),
                "exam_forms": len(forms),
            })
        return sorted(lessons, key=lambda item: (-item["priority"], item["exercise_id"]))

    def accreditation(self, exercises, history):
        categories = {exercise.category for exercise in exercises}
        skill_evidence = {}
        for skill in sorted(categories):
            required_difficulty = min(MIN_DIFFICULTY, max(
                exercise.difficulty for exercise in exercises if exercise.category == skill))
            passed = [item for item in history
                      if item.get("category") == skill and item.get("verified_pass")]
            forms = {exam_form(item.get("exercise_id", ""), item.get("sequence", 0))
                     for item in passed}
            score = round(sum(float(item.get("score", 0)) for item in passed) / len(passed), 1) if passed else 0
            difficulty = max((int(item.get("difficulty", 0)) for item in passed), default=0)
            qualified = (len(passed) >= MIN_PASSES and len(forms) >= MIN_EXAM_FORMS
                         and score >= MIN_SCORE and difficulty >= required_difficulty)
            skill_evidence[skill] = {"qualified": qualified, "passes": len(passed),
                                     "exam_forms": len(forms), "average_score": score,
                                     "max_difficulty": difficulty,
                                     "required_difficulty": required_difficulty}

        domains = []
        for domain, expected in DOMAIN_MAP.items():
            available = expected & categories
            qualified = sorted(skill for skill in available
                               if skill_evidence.get(skill, {}).get("qualified"))
            coverage = round(len(qualified) / len(available), 3) if available else 0
            status = "ACCREDITED" if available and coverage == 1 else "DEVELOPING"
            payload = {"standard": ACCREDITATION_STANDARD, "domain": domain,
                       "status": status, "coverage": coverage,
                       "qualified_skills": qualified, "required_skills": sorted(available)}
            payload["credential_id"] = sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:20]
            domains.append(payload)

        qualified_skills = sorted(skill for skill, evidence in skill_evidence.items()
                                  if evidence["qualified"])
        return {
            "issuer": "Bounty Builder internal evidence board",
            "standard": ACCREDITATION_STANDARD,
            "third_party_accreditation": False,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "ACCREDITED" if domains and all(d["status"] == "ACCREDITED" for d in domains)
                      else "DEVELOPING",
            "qualified_to_teach": qualified_skills,
            "not_yet_qualified": sorted(categories - set(qualified_skills)),
            "domains": domains,
            "skill_evidence": skill_evidence,
        }

    def cycle(self, exercises, history, limit=10):
        curriculum = self.curriculum(exercises, history)
        accreditation = self.accreditation(exercises, history)
        payload = {"curriculum": curriculum[:max(1, min(int(limit), 20))],
                   "accreditation": accreditation,
                   "knowledge_policy": {
                       "internet_content_is_untrusted": True,
                       "citations_required_for_research": True,
                       "policy_self_modification": False,
                       "external_actions": False,
                   }}
        stable = {**payload, "accreditation": {k: v for k, v in accreditation.items()
                                                if k != "generated_at"}}
        payload["cycle_id"] = sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()[:20]
        return payload
