import unittest
import os
import tempfile

from coding_gym import CodingGym, EXERCISES
from store import Store


class CodingGymTests(unittest.TestCase):
    def test_fail_then_pass_drill_records_verified_evidence(self):
        statuses = iter(("FAILED", "PASSED"))
        gym = CodingGym(lambda _files, _profile: {
            "status": next(statuses), "network": "disabled"})
        result = gym.run(0)
        self.assertTrue(result["verified_pass"])
        self.assertEqual(100, result["score"])
        self.assertTrue(result["practice_only"])
        self.assertEqual("disabled", result["network"])

    def test_rotation_covers_every_exercise(self):
        gym = CodingGym(lambda _files, _profile: {
            "status": "FAILED", "network": "disabled"})
        seen = {gym.run(i)["exercise_id"] for i in range(len(EXERCISES))}
        self.assertEqual({exercise.exercise_id for exercise in EXERCISES}, seen)

    def test_does_not_store_source_code_in_result(self):
        gym = CodingGym(lambda _files, _profile: {
            "status": "PASSED", "network": "disabled"})
        result = gym.run(0)
        self.assertNotIn("solution", result)
        self.assertNotIn("starter", result)
        self.assertNotIn("tests", result)

    def test_repeated_drills_keep_distinct_evidence(self):
        gym = CodingGym(lambda _files, _profile: {
            "status": "PASSED", "network": "disabled"})
        self.assertNotEqual(gym.run(0)["evidence_id"], gym.run(4)["evidence_id"])

    def test_store_counts_drills_and_verified_passes(self):
        statuses = iter(("FAILED", "PASSED"))
        result = CodingGym(lambda _files, _profile: {
            "status": next(statuses), "network": "disabled"}).run(0)
        with tempfile.TemporaryDirectory() as directory:
            store = Store(os.path.join(directory, "gym.db"))
            self.assertEqual(1, store.save_practice_run(result))
            self.assertEqual(0, store.save_practice_run(result))
            self.assertEqual({"drills": 1, "verified_passes": 1,
                              "average_score": 100.0, "max_difficulty": 1},
                             store.practice_stats())


if __name__ == "__main__":
    unittest.main()
