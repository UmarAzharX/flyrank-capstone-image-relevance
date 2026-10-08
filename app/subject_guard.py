import re
from dataclasses import dataclass
from typing import Literal


SUBJECT_PATTERNS = {
    "fox": r"\bfox(?:es)?\b",
    "wolf": r"\b(?:wolf|wolves)\b",
    "dog": (
        r"\b(?:dogs?|husk(?:y|ies)|malamutes?"
        r"|german\s+shepherds?)\b"
    ),
    "bear": r"\b(?:bears?|grizzl(?:y|ies))\b",
    "deer": r"\bdeer\b",
    "antelope": r"\bantelopes?\b",
}


@dataclass(frozen=True)
class SubjectGuardResult:
    decision: Literal["pass", "reject", "review"]
    explanation: str


def _subjects_in(text: str) -> set[str]:
    return {
        subject
        for subject, pattern in SUBJECT_PATTERNS.items()
        if re.search(pattern, text, flags=re.IGNORECASE)
    }


def evaluate_subject_match(
    *,
    post_title: str,
    post_content: str,
    image_subject: str,
) -> SubjectGuardResult:
    post_subjects = _subjects_in(
        f"{post_title}\n{post_content}"
    )
    image_subjects = _subjects_in(image_subject)

    if len(post_subjects) != 1 or len(image_subjects) != 1:
        return SubjectGuardResult(
            decision="review",
            explanation=(
                "Could not identify one clear, supported animal "
                "subject on both sides."
            ),
        )

    post_subject = next(iter(post_subjects))
    image_subject = next(iter(image_subjects))

    if post_subject != image_subject:
        return SubjectGuardResult(
            decision="reject",
            explanation=(
                f"Subject mismatch: post describes {post_subject}; "
                f"image describes {image_subject}."
            ),
        )

    return SubjectGuardResult(
        decision="pass",
        explanation=(
            f"Subject check passed: both describe {post_subject}."
        ),
    )
