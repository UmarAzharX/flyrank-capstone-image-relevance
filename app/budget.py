from decimal import Decimal


class AIUsageLimitError(RuntimeError):
    pass


def check_ai_limits(
    *,
    spent_usd: float,
    recorded_calls: int,
    budget_usd: float,
    max_calls: int,
    estimated_call_cost_usd: float,
) -> None:
    amounts = [
        Decimal(str(spent_usd)),
        Decimal(str(budget_usd)),
        Decimal(str(estimated_call_cost_usd)),
    ]

    if any(not amount.is_finite() or amount < 0 for amount in amounts):
        raise ValueError("Dollar amounts must be finite and nonnegative.")

    if recorded_calls < 0 or max_calls < 0:
        raise ValueError("Call counts must be nonnegative.")

    if recorded_calls >= max_calls:
        raise AIUsageLimitError("AI call limit reached.")

    spent, budget, next_cost = amounts

    if spent + next_cost > budget:
        raise AIUsageLimitError("The next call would exceed the AI budget.")