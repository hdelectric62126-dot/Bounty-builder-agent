import unittest

from solution_planner import PlanningError, create_solution_plan


class SolutionPlannerTests(unittest.TestCase):
    def setUp(self):
        self.opportunity = {
            "external_id": "issue-42",
            "title": "Fix bounded parser bug",
            "status": "APPROVED",
        }
        self.analysis = {
            "complexity": "low",
            "relevant_files": ["parser.py", "tests/test_parser.py"],
            "requirements": ["Reject malformed records", "Keep valid records compatible"],
            "test_commands": ["pytest -q"],
            "unknowns": ["Exact malformed fixture is not documented"],
        }

    def test_creates_proposal_with_explicit_human_checkpoint(self):
        plan = create_solution_plan(self.opportunity, self.analysis)
        self.assertEqual("AWAITING_HUMAN_APPROVAL", plan.approval_status)
        self.assertIn("Daniel", plan.approval_checkpoint)
        self.assertIn("execute_code", plan.prohibited_actions)
        self.assertIn("submit_solution", plan.prohibited_actions)
        self.assertGreater(plan.estimated_hours, 0)
        self.assertTrue(any("pytest -q" in item for item in plan.test_checklist))

    def test_refuses_unapproved_opportunity(self):
        self.opportunity["status"] = "REJECTED"
        with self.assertRaises(PlanningError):
            create_solution_plan(self.opportunity, self.analysis)

    def test_filters_unsafe_file_paths(self):
        self.analysis["relevant_files"] = ["src/app.py", "../../etc/passwd", "/root/key"]
        plan = create_solution_plan(self.opportunity, self.analysis)
        self.assertEqual(("src/app.py",), plan.steps[1].files)

    def test_output_is_serializable_and_bounded(self):
        plan = create_solution_plan(self.opportunity, self.analysis).to_dict()
        self.assertEqual("issue-42", plan["opportunity_id"])
        self.assertLessEqual(plan["confidence"], 0.9)
        self.assertEqual(4, len(plan["steps"]))


if __name__ == "__main__":
    unittest.main()
