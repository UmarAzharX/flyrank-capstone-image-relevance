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


DOG_BREED_PATTERNS = {
    "husky": r"\bhusk(?:y|ies)\b",
    "malamute": r"\bmalamutes?\b",
    "german shepherd": r"\bgerman\s+shepherds?\b",
}


def _dog_breeds_in(text: str) -> set[str]:
    return {
        breed
        for breed, pattern in DOG_BREED_PATTERNS.items()
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

    image_description = image_subject
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

    if post_subject == "dog":
        requested = _dog_breeds_in(f"{post_title}\n{post_content}")
        if len(requested) > 1:
            return SubjectGuardResult(
                "review", "Post names multiple supported dog breeds."
            )
        if requested:
            observed = _dog_breeds_in(image_description)
            if len(observed) != 1:
                return SubjectGuardResult(
                    "review",
                    "Image subject does not confirm one clear dog breed "
                    "for this breed-specific post.",
                )
            wanted = next(iter(requested))
            actual = next(iter(observed))
            if wanted != actual:
                return SubjectGuardResult(
                    "reject",
                    f"Dog breed mismatch: post describes {wanted}; "
                    f"image describes {actual}.",
                )
            return SubjectGuardResult(
                "pass", f"Subject check passed: both describe {wanted}."
            )

    return SubjectGuardResult(
        decision="pass",
        explanation=(
            f"Subject check passed: both describe {post_subject}."
        ),
    )
