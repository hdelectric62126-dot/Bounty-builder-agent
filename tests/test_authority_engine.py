import unittest

from authority_engine import capability_certificates, decide_authority


def profile(passes=2):
    return {"skills": {"testing_quality": {"verified_passes": passes,
            "average_score": 100, "max_difficulty": 5}}}


class AuthorityEngineTests(unittest.TestCase):
    def test_issues_evidence_bound_certificate(self):
        certificate = capability_certificates(profile())[0]
        self.assertEqual("VERIFIED", certificate["tier"])
        self.assertEqual(20, len(certificate["certificate_id"]))

    def test_internal_package_requires_complete_evidence(self):
        evidence = {"isolation": "railway_ephemeral_vm", "credentials_injected": False,
                    "sandbox_status": "PASSED", "workspace_destroyed": True,
                    "inspection": {"passed": True},
                    "review_consensus": {"unanimous": True}}
        decision = decide_authority("package_for_review", evidence,
                                    ["testing_quality"], profile())
        self.assertTrue(decision["authorized"])
        self.assertEqual("AUTO_APPROVED_INTERNAL", decision["status"])

    def test_provisional_skill_cannot_approve_build(self):
        evidence = {"isolation": "railway_ephemeral_vm", "credentials_injected": False}
        decision = decide_authority("isolated_build", evidence,
                                    ["testing_quality"], profile(1))
        self.assertFalse(decision["authorized"])
        self.assertIn("uncertified_skill:testing_quality", decision["reasons"])

    def test_external_actions_always_require_daniel(self):
        for action in ("accept_contract", "charge_payment", "public_submission",
                       "merge_client_code", "final_delivery"):
            with self.subTest(action=action):
                decision = decide_authority(action, {}, [], profile(10))
                self.assertFalse(decision["authorized"])
                self.assertEqual("DANIEL_APPROVAL_REQUIRED", decision["status"])

    def test_unknown_authority_is_denied(self):
        self.assertEqual("DENIED", decide_authority("become_admin", {}, [], profile())["status"])


if __name__ == "__main__":
    unittest.main()
