import unittest

from risk_compliance_agent import OpportunityRiskInput, evaluate_risk


def valid_item(**overrides):
    values = dict(
        reward=500,
        success_probability=0.65,
        estimated_hours=8,
        cash_cost=5,
        hourly_cost=5,
        license_ok=True,
        terms_ok=True,
        payment_confidence=0.9,
        scope_ambiguity=2,
        legal_risk=1,
    )
    values.update(overrides)
    return OpportunityRiskInput(**values)


class RiskComplianceAgentTests(unittest.TestCase):
    def test_approves_positive_bounded_opportunity(self):
        result = evaluate_risk(valid_item())
        self.assertTrue(result.approved)
        self.assertEqual("APPROVED", result.status)
        self.assertEqual(247.5, result.expected_value)
        self.assertEqual(("APPROVE_WITHIN_POLICY",), result.reason_codes)

    def test_all_hard_stops_are_reported_in_stable_order(self):
        result = evaluate_risk(valid_item(
            cash_cost=30, license_ok=False, terms_ok=False,
            payment_confidence=0.4, scope_ambiguity=8, legal_risk=4,
        ))
        self.assertFalse(result.approved)
        self.assertEqual(0, result.score)
        self.assertEqual((
            "HARD_STOP_CASH_LIMIT",
            "HARD_STOP_LICENSE",
            "HARD_STOP_TERMS",
            "HARD_STOP_PAYMENT_CONFIDENCE",
            "HARD_STOP_SCOPE_AMBIGUITY",
            "HARD_STOP_LEGAL_RISK",
        ), result.reason_codes)

    def test_payment_confidence_changes_expected_value(self):
        high = evaluate_risk(valid_item(payment_confidence=0.9))
        low = evaluate_risk(valid_item(payment_confidence=0.6))
        self.assertGreater(high.expected_value, low.expected_value)

    def test_negative_ev_is_rejected_after_compliance_passes(self):
        result = evaluate_risk(valid_item(
            reward=50, success_probability=0.2, payment_confidence=0.6,
            estimated_hours=10, hourly_cost=10,
        ))
        self.assertFalse(result.approved)
        self.assertIn("REJECT_EXPECTED_VALUE", result.reason_codes)

    def test_decision_and_audit_record_are_deterministic(self):
        first = evaluate_risk(valid_item())
        second = evaluate_risk(valid_item())
        self.assertEqual(first.decision_id, second.decision_id)
        self.assertEqual(first.audit_record, second.audit_record)
        self.assertEqual(first.decision_id, first.audit_record["decision_id"])

    def test_invalid_probabilities_fail_closed(self):
        result = evaluate_risk(valid_item(success_probability=1.1))
        self.assertFalse(result.approved)
        self.assertIn("HARD_STOP_INVALID_SUCCESS_PROBABILITY", result.reason_codes)

    def test_assigned_work_is_rejected(self):
        result = evaluate_risk(valid_item(assigned=True))
        self.assertFalse(result.approved)
        self.assertIn("HARD_STOP_ALREADY_ASSIGNED", result.reason_codes)

    def test_overcompeted_work_is_rejected(self):
        result = evaluate_risk(valid_item(competing_pull_requests=3))
        self.assertFalse(result.approved)
        self.assertIn("HARD_STOP_OVERCOMPETED", result.reason_codes)

    def test_two_competing_pull_requests_remain_eligible(self):
        result = evaluate_risk(valid_item(competing_pull_requests=2))
        self.assertTrue(result.approved)

    def test_unverified_competition_fails_closed(self):
        result = evaluate_risk(valid_item(competition_data_complete=False))
        self.assertFalse(result.approved)
        self.assertIn("HARD_STOP_COMPETITION_UNVERIFIED", result.reason_codes)


if __name__ == "__main__":
    unittest.main()
