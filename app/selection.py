from app.mismatch_guard import MismatchGuardResult
from app.ranking import RankedImage


GuardedCandidate = tuple[RankedImage, MismatchGuardResult]


def select_eligible_candidates(
    candidates: list[GuardedCandidate],
    *,
    limit: int,
) -> list[GuardedCandidate]:
    if type(limit) is not int or limit < 1:
        raise ValueError("Suggestion limit must be a positive integer.")

    eligible = [
        candidate
        for candidate in candidates
        if candidate[1].decision == "pass"
    ]
    eligible.sort(
        key=lambda candidate: (
            -candidate[0].similarity_score,
            candidate[0].external_id,
        )
    )
    return eligible[:limit]
