import math

from app.embedding_vectors import validate_and_normalize_vector


def cosine_similarity(
    first: list[float],
    second: list[float],
) -> float:
    first_unit = validate_and_normalize_vector(first)
    second_unit = validate_and_normalize_vector(second)

    score = math.fsum(
        a * b
        for a, b in zip(first_unit, second_unit, strict=True)
    )

    return max(-1.0, min(1.0, score))
