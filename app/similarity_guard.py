import math
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SimilarityGuardResult:
    decision: Literal["pass", "reject", "review"]
    explanation: str


def _valid_cosine(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and -1.0 <= value <= 1.0


def evaluate_similarity(*, score: float | None, threshold: float) -> SimilarityGuardResult:
    if not _valid_cosine(threshold):
        raise ValueError("Similarity threshold must be finite and between -1 and 1.")
    if not _valid_cosine(score):
        return SimilarityGuardResult("review", "Cosine similarity is missing or invalid.")
    if score < threshold:
        return SimilarityGuardResult(
            "reject",
            f"Cosine similarity {score!r} is below the configured cutoff {threshold!r}.",
        )
    return SimilarityGuardResult(
        "pass",
        f"Cosine similarity {score:.6f} meets the configured cutoff {threshold:.3f}.",
    )
