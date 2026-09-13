import unittest

from coding_gym import EXERCISES
from training_scheduler import plan_training


class TrainingSchedulerTests(unittest.TestCase):
    def test_empty_history_prioritizes_advanced_unverified_skills(self):
        plan = plan_training(EXERCISES, [], 3)
        self.assertEqual(3, len(plan))
        self.assertTrue(all(item["reason"] == "UNVERIFIED_SKILL" for item in plan))
        self.assertEqual(sorted((x["difficulty"] for x in plan), reverse=True),
                         [x["difficulty"] for x in plan])

    def test_prioritizes_only_missing_exercise(self):
        history = [{"exercise_id": exercise.exercise_id, "sequence": index,
                    "verified_pass": exercise.exercise_id != "migration-plan",
                    "language": exercise.language}
                   for index, exercise in enumerate(EXERCISES)]
        plan = plan_training(EXERCISES, history, 1)
        self.assertEqual("migration-plan", plan[0]["exercise_id"])
        self.assertEqual("UNVERIFIED_SKILL", plan[0]["reason"])

    def test_sequences_are_unique_and_new(self):
        history = [{"exercise_id": EXERCISES[0].exercise_id, "sequence": 100,
                    "verified_pass": True, "language": "python"}]
        plan = plan_training(EXERCISES, history, 10)
        sequences = [item["sequence"] for item in plan]
        self.assertEqual(len(sequences), len(set(sequences)))
        self.assertTrue(all(sequence > 100 for sequence in sequences))

    def test_rounds_are_capped_to_catalog(self):
        self.assertEqual(len(EXERCISES), len(plan_training(EXERCISES, [], 10_000)))


if __name__ == "__main__":
    unittest.main()
