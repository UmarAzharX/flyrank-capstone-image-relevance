import unittest

from app.budget import AIUsageLimitError, check_ai_limits


class BudgetTests(unittest.TestCase):
    def check(self, **overrides):
        values = {
            "spent_usd": 0.0,
            "recorded_calls": 7,
            "budget_usd": 0.0,
            "max_calls": 200,
            "estimated_call_cost_usd": 0.0,
        }
        values.update(overrides)
        check_ai_limits(**values)

    def test_free_call_allowed_with_zero_budget(self):
        self.check()

    def test_paid_call_blocked_with_zero_budget(self):
        with self.assertRaises(AIUsageLimitError):
            self.check(estimated_call_cost_usd=0.01)

    def test_call_cap_blocks_even_free_calls(self):
        with self.assertRaises(AIUsageLimitError):
            self.check(recorded_calls=200)

    def test_exact_budget_allowed(self):
        self.check(
            spent_usd=0.1,
            budget_usd=0.3,
            estimated_call_cost_usd=0.2,
        )

    def test_invalid_amounts_rejected(self):
        for amount in (-0.01, float("inf"), float("nan")):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    self.check(budget_usd=amount)


if __name__ == "__main__":
    unittest.main()