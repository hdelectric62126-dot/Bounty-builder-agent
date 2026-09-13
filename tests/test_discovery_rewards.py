import unittest

from discovery import parse_reward_claim


class RewardClaimTests(unittest.TestCase):
    def test_accepts_normal_bounty(self):
        self.assertEqual((1250.0, True), parse_reward_claim("Bounty: $1,250.00"))

    def test_quarantines_spam_sized_claim(self):
        reward, valid = parse_reward_claim("$999999999999999999999999 BOUNTY")
        self.assertEqual(0.0, reward)
        self.assertFalse(valid)

    def test_one_oversized_claim_invalidates_the_entire_issue(self):
        self.assertEqual((0.0, False), parse_reward_claim("$500 or $999999999999999999"))


if __name__ == "__main__": unittest.main()
