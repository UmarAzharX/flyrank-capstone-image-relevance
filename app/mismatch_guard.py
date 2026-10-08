from dataclasses import dataclass
from typing import Literal

from app.context_guard import evaluate_winter_context
from app.subject_guard import evaluate_subject_match


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
) -> MismatchGuardResult:
    subject = evaluate_subject_match(
        post_title=post_title,
        post_content=post_content,
        image_subject=image_subject,
    )
    context = evaluate_winter_context(
        post_title=post_title,
        post_content=post_content,
        image_caption=image_caption,
        image_attributes=image_attributes,
    )

    explanation = f"{subject.explanation} {context.explanation}"

    if subject.decision == "reject" or context.decision == "reject":
        return MismatchGuardResult("reject", explanation)

    if context.decision == "not_applicable":
        explanation += " Other habitat requirements need review."

    if (
        subject.decision == "review"
        or context.decision in {"review", "not_applicable"}
    ):
        return MismatchGuardResult("review", explanation)

    return MismatchGuardResult("pass", explanation)
