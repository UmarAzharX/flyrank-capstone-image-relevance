from dataclasses import dataclass
from typing import Literal

from app.confidence_guard import evaluate_vision_confidence
from app.context_guard import evaluate_context_match
from app.subject_guard import evaluate_subject_match
from app.similarity_guard import evaluate_similarity


@dataclass(frozen=True)
class MismatchGuardResult:
    decision: Literal["pass", "reject", "review"]
    explanation: str


def evaluate_mismatch(
    *,
    post_title: str,
    post_content: str,
    image_subject: str,
    image_caption: str,
    image_attributes: list[str],
    image_confidence: float | None,
    confidence_threshold: float,
    similarity_score: float | None,
    similarity_threshold: float,
) -> MismatchGuardResult:
    subject = evaluate_subject_match(
        post_title=post_title,
        post_content=post_content,
        image_subject=image_subject,
    )
    context = evaluate_context_match(
        post_title=post_title,
        post_content=post_content,
        image_caption=image_caption,
        image_attributes=image_attributes,
    )
    confidence = evaluate_vision_confidence(
        confidence=image_confidence,
        threshold=confidence_threshold,
    )

    similarity = evaluate_similarity(
        score=similarity_score, threshold=similarity_threshold,
    )

    explanation = " ".join([
        subject.explanation,
        context.explanation,
        confidence.explanation,
        similarity.explanation,
    ])

    if (
        subject.decision == "reject"
        or context.decision == "reject"
        or similarity.decision == "reject"
    ):
        return MismatchGuardResult("reject", explanation)

    if context.decision == "not_applicable":
        explanation += " Context requirements need review."

    if (
        subject.decision == "review"
        or context.decision in {"review", "not_applicable"}
        or confidence.decision == "review"
        or similarity.decision == "review"
    ):
        return MismatchGuardResult("review", explanation)

    return MismatchGuardResult("pass", explanation)
