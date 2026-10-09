import re
from dataclasses import dataclass
from typing import Literal


WINTER = re.compile(r"\b(?:winter|wintry)\b", re.IGNORECASE)
SNOW = re.compile(r"\bsnow(?:y|fall)?\b", re.IGNORECASE)
OTHER_SEASON = re.compile(
    r"\b(?:summer|autumn|spring)\b", re.IGNORECASE
)
NEGATED_CONTEXT = re.compile(
    r"\b(?:no|not|without)\s+(?:\w+\s+){0,2}(?:snow|winter)\b"
    r"|\b(?:snow|winter)[ -]free\b|\bsnowless\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ContextGuardResult:
    decision: Literal["pass", "reject", "review", "not_applicable"]
    explanation: str


def evaluate_winter_context(
    *,
    post_title: str,
    post_content: str,
    image_caption: str,
    image_attributes: list[str],
) -> ContextGuardResult:
    post_text = f"{post_title}\n{post_content}"
    image_text = "\n".join([image_caption, *image_attributes])

    needs_winter = bool(WINTER.search(post_text))
    needs_snow = bool(SNOW.search(post_text))

    if not needs_winter and not needs_snow:
        return ContextGuardResult(
            "not_applicable",
            "No winter or snow requirement detected by this rule.",
        )

    if (
        NEGATED_CONTEXT.search(post_text)
        or NEGATED_CONTEXT.search(image_text)
    ):
        return ContextGuardResult(
            "review",
            "Negated winter/snow wording needs context review.",
        )

    if needs_winter and OTHER_SEASON.search(post_text):
        return ContextGuardResult(
            "review",
            "Post mentions winter and another season.",
        )

    image_winter = bool(WINTER.search(image_text))
    image_snow = bool(SNOW.search(image_text))

    if needs_winter and OTHER_SEASON.search(image_text):
        if image_winter:
            return ContextGuardResult(
                "review",
                "Image metadata mentions conflicting seasons.",
            )
        return ContextGuardResult(
            "reject",
            "Season mismatch: winter post; image metadata "
            "explicitly describes another season.",
        )

    if needs_snow and not image_snow:
        return ContextGuardResult(
            "review",
            "Post requests snow, but image metadata "
            "does not confirm snow.",
        )

    if needs_winter and not (image_winter or image_snow):
        return ContextGuardResult(
            "review",
            "Post describes winter, but image metadata "
            "does not confirm winter or snowy surroundings.",
        )

    return ContextGuardResult(
        "pass",
        "Winter/snow context is supported by image metadata.",
    )


HABITAT_PATTERNS = {
    "woodland": r"\b(?:forests?|woodlands?|woods|wooded)\b",
    "grassland": r"\b(?:grass|grasses|grasslands?|meadows?|lawns?)\b",
    "indoor setting": r"\b(?:homes?|houses?|indoors?|living\s+room)\b",
    "road": r"\b(?:roads?|asphalt|pavement|streets?|urban|city|town)\b",
    "close-up view": r"\bclose(?:[- ]up|\s+(?:view|portrait))\b",
}

HABITAT_OUTDOOR = re.compile(
    r"\b(?:outdoors?|outside)\b", re.IGNORECASE
)
HABITAT_NEGATED = re.compile(
    r"\b(?:no|not|without)\s+(?:\w+\s+){0,2}"
    r"(?:forests?|woodlands?|woods|grass|meadows?|lawns?"
    r"|home|indoors?|outdoors?|outside|roads?|streets?"
    r"|close[- ]up)\b"
    r"|\b(?:forest|grass|road)[ -]free\b",
    re.IGNORECASE,
)


def _habitats_in(text: str) -> set[str]:
    return {
        habitat
        for habitat, pattern in HABITAT_PATTERNS.items()
        if re.search(pattern, text, flags=re.IGNORECASE)
    }


def evaluate_habitat_context(
    *,
    post_title: str,
    post_content: str,
    image_caption: str,
    image_attributes: list[str],
) -> ContextGuardResult:
    post_text = f"{post_title}\n{post_content}"
    image_text = "\n".join([image_caption, *image_attributes])
    required = _habitats_in(post_text)

    if not required:
        return ContextGuardResult(
            "not_applicable",
            "No supported habitat or framing requirement detected.",
        )

    if (
        HABITAT_NEGATED.search(post_text)
        or HABITAT_NEGATED.search(image_text)
    ):
        return ContextGuardResult(
            "review",
            "Negated habitat wording needs context review.",
        )

    present = _habitats_in(image_text)

    if "indoor setting" in required:
        if HABITAT_OUTDOOR.search(post_text):
            return ContextGuardResult(
                "review",
                "Post mixes indoor and outdoor settings.",
            )

        if HABITAT_OUTDOOR.search(image_text):
            if "indoor setting" in present:
                return ContextGuardResult(
                    "review",
                    "Image metadata mixes indoor and outdoor settings.",
                )
            return ContextGuardResult(
                "reject",
                "Setting mismatch: post requests an indoor setting; "
                "image metadata explicitly describes outdoors.",
            )

    missing = required - present
    if missing:
        return ContextGuardResult(
            "review",
            "Image metadata does not confirm required context: "
            + ", ".join(sorted(missing))
            + ".",
        )

    return ContextGuardResult(
        "pass",
        "Image metadata supports the requested context: "
        + ", ".join(sorted(required))
        + ".",
    )
