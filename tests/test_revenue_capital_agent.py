import unittest

from revenue_capital_agent import evaluate_capital


class RevenueCapitalAgentTests(unittest.TestCase):
    def snapshot(self):
        return {"available_cash_cents": 80000, "total_credit_limit_cents": 500000,
                "total_credit_balance_cents": 50000, "monthly_spending": [
                    {"label": "Rent", "category": "housing", "amount_cents": 100000},
                    {"label": "Unused app", "category": "subscription", "amount_cents": 2500},
                ]}

    def test_protects_essentials_and_flags_redirectable_spend(self):
        plan = evaluate_capital(self.snapshot(), [])
        self.assertEqual(100000, plan["protected_monthly_spending_cents"])
        self.assertEqual(2500, plan["redirectable_monthly_spending_cents"])
        self.assertEqual("REVIEW_OR_REDIRECT", plan["redirectable_items"][0]["recommendation"])

    def test_qualifies_evidence_backed_positive_fast_return(self):
        plan = evaluate_capital(self.snapshot(), [{"name": "software job", "cost_cents": 20000,
            "gross_revenue_cents": 70000, "finance_cost_cents": 1000,
            "success_probability": .8, "payback_days": 30, "evidence": "signed scope"}])
        self.assertEqual("QUALIFIED", plan["opportunities"][0]["decision"])
        self.assertEqual(35000, plan["opportunities"][0]["expected_profit_cents"])

    def test_rejects_negative_ev_and_missing_evidence(self):
        plan = evaluate_capital(self.snapshot(), [{"name": "ad spend", "cost_cents": 50000,
            "gross_revenue_cents": 30000, "success_probability": .5,
            "payback_days": 30, "evidence": ""}])
        result = plan["opportunities"][0]
        self.assertEqual("REJECTED", result["decision"])
        self.assertIn("NON_POSITIVE_EXPECTED_PROFIT", result["reasons"])
        self.assertIn("MISSING_REVENUE_EVIDENCE", result["reasons"])

    def test_available_credit_is_not_treated_as_income(self):
        plan = evaluate_capital(self.snapshot(), [])
        self.assertFalse(plan["credit"]["available_credit_is_income"])
        self.assertEqual(50000, plan["credit"]["qualified_capacity_cents"])

    def test_invalid_probability_fails_closed(self):
        with self.assertRaises(ValueError):
            evaluate_capital(self.snapshot(), [{"cost_cents": 1, "gross_revenue_cents": 2,
                "success_probability": 2, "payback_days": 1, "evidence": "x"}])


if __name__ == "__main__":
    unittest.main()
