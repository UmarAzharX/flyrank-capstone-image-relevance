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


SEASON_WORDS = re.compile(
    r"\b(?:winter|wintry|summer|autumn|spring|springtime)\b",
    re.IGNORECASE,
)
COLD_WEATHER = re.compile(
    r"\b(?:cold|freezing|frozen|icy|ice)\b",
    re.IGNORECASE,
)
SEASON_NEGATED = re.compile(
    r"\b(?:no|not|without)\s+(?:\w+\s+){0,2}"
    r"(?:winter|summer|autumn|spring|cold|freezing|frozen"
    r"|snow(?:y|fall)?|ice|icy)\b"
    r"|\b(?:snow|winter)[ -]free\b|\bsnowless\b",
    re.IGNORECASE,
)


def _seasons_in(text: str) -> set[str]:
    aliases = {"wintry": "winter", "springtime": "spring"}
    words = {
        match.group(0).casefold()
        for match in SEASON_WORDS.finditer(text)
    }
    return {aliases.get(word, word) for word in words}


def evaluate_season_context(
    *,
    post_title: str,
    post_content: str,
    image_caption: str,
    image_attributes: list[str],
) -> ContextGuardResult:
    post_text = f"{post_title}\n{post_content}"
    image_text = "\n".join([image_caption, *image_attributes])
    requested = _seasons_in(post_text)
    needs_cold = bool(COLD_WEATHER.search(post_text))

    if not requested and not needs_cold:
        return ContextGuardResult(
            "not_applicable",
            "No season or cold-weather requirement detected.",
        )

    if len(requested) > 1:
        return ContextGuardResult(
            "review",
            "Post mentions multiple seasons.",
        )

    if (
        SEASON_NEGATED.search(post_text)
        or SEASON_NEGATED.search(image_text)
    ):
        return ContextGuardResult(
            "review",
            "Negated seasonal wording needs context review.",
        )

    explanations = []
    season = next(iter(requested), None)

    if season is not None:
        observed = _seasons_in(image_text)

        if len(observed) > 1:
            return ContextGuardResult(
                "review",
                "Image metadata mentions multiple seasons.",
            )

        if observed and season not in observed:
            return ContextGuardResult(
                "reject",
                f"Season mismatch: post requests {season}; "
                f"image metadata describes {next(iter(observed))}.",
            )

        if season != "winter" and season not in observed:
            return ContextGuardResult(
                "review",
                f"Image metadata does not confirm {season}.",
            )

        if season in observed:
            explanations.append(
                f"Image metadata confirms {season}."
            )

    if needs_cold:
        cold_evidence = (
            COLD_WEATHER.search(image_text)
            or WINTER.search(image_text)
            or SNOW.search(image_text)
        )
        if not cold_evidence:
            return ContextGuardResult(
                "review",
                "Image metadata does not confirm cold-weather context.",
            )
        explanations.append(
            "Cold-weather context is supported by image metadata."
        )

    if not explanations:
        return ContextGuardResult(
            "not_applicable",
            "Winter evidence is evaluated by the winter/snow check.",
        )

    return ContextGuardResult("pass", " ".join(explanations))


def evaluate_context_match(
    *,
    post_title: str,
    post_content: str,
    image_caption: str,
    image_attributes: list[str],
) -> ContextGuardResult:
    checks = [
        evaluator(
            post_title=post_title,
            post_content=post_content,
            image_caption=image_caption,
            image_attributes=image_attributes,
        )
        for evaluator in (
            evaluate_winter_context,
            evaluate_habitat_context,
            evaluate_season_context,
        )
    ]
    active = [
        result
        for result in checks
        if result.decision != "not_applicable"
    ]

    if not active:
        return ContextGuardResult(
            "not_applicable",
            "No supported context requirement was identified.",
        )

    explanation = " ".join(result.explanation for result in active)
    if any(result.decision == "reject" for result in active):
        return ContextGuardResult("reject", explanation)
    if any(result.decision == "review" for result in active):
        return ContextGuardResult("review", explanation)
    return ContextGuardResult("pass", explanation)
