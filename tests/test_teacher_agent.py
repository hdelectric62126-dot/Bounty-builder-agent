import unittest

from coding_gym import EXERCISES
from teacher_agent import TeacherAgent, exam_form


class TeacherAgentTests(unittest.TestCase):
    def setUp(self):
        self.teacher = TeacherAgent()

    def test_unproven_teacher_does_not_claim_accreditation(self):
        report = self.teacher.accreditation(EXERCISES, [])
        self.assertEqual("DEVELOPING", report["status"])
        self.assertFalse(report["third_party_accreditation"])
        self.assertEqual([], report["qualified_to_teach"])

    def test_requires_diverse_exam_forms(self):
        exercise = next(item for item in EXERCISES if item.category == "testing_quality")
        history = [{"exercise_id": exercise.exercise_id, "category": exercise.category,
                    "sequence": sequence, "difficulty": 5, "score": 100,
                    "verified_pass": True} for sequence in (1, 2, 3)]
        report = self.teacher.accreditation((exercise,), history)
        self.assertFalse(report["skill_evidence"][exercise.category]["qualified"])
        history[-1]["sequence"] = 48
        report = self.teacher.accreditation((exercise,), history)
        self.assertTrue(report["skill_evidence"][exercise.category]["qualified"])

    def test_failed_skill_is_prioritized_for_remediation(self):
        exercise = EXERCISES[0]
        history = [{"exercise_id": exercise.exercise_id, "category": exercise.category,
                    "sequence": 0, "difficulty": exercise.difficulty, "score": 0,
                    "verified_pass": False}]
        lesson = self.teacher.curriculum((exercise,), history)[0]
        self.assertIn("REMEDIATION_REQUIRED", lesson["reasons"])

    def test_cycle_has_stable_evidence_identity(self):
        first = self.teacher.cycle(EXERCISES, [])
        second = self.teacher.cycle(EXERCISES, [])
        self.assertEqual(first["cycle_id"], second["cycle_id"])
        self.assertEqual(12, len(exam_form("x", 1)))


if __name__ == "__main__":
    unittest.main()
