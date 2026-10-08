import math
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ConfidenceGuardResult:
    decision: Literal["pass", "review"]
    explanation: str


def _valid_score(value: object) -> bool:
    return (
        type(value) in (int, float)
        and 0.0 <= value <= 1.0
        and math.isfinite(value)
    )


def evaluate_vision_confidence(
    *,
    confidence: float | None,
    threshold: float,
) -> ConfidenceGuardResult:
    if not _valid_score(threshold):
        raise ValueError("Confidence threshold must be between 0 and 1.")

    if not _valid_score(confidence):
        return ConfidenceGuardResult(
            "review",
            "Vision confidence is missing or invalid.",
        )

    if confidence < threshold:
        return ConfidenceGuardResult(
            "review",
            f"Vision confidence {confidence:.3f} is below "
            f"the configured threshold {threshold:.3f}.",
        )

    return ConfidenceGuardResult(
        "pass",
        f"Vision confidence {confidence:.3f} meets "
        f"the configured threshold {threshold:.3f}.",
    )
