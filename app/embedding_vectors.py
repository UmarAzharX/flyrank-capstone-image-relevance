import math


EMBEDDING_MODEL = "gemini-embedding-2"
EMBEDDING_DIMENSIONS = 768
EMBEDDING_PROFILE = (
    f"{EMBEDDING_MODEL}:{EMBEDDING_DIMENSIONS}:retrieval:text-v1"
)


def validate_and_normalize_vector(values: list[float]) -> list[float]:
    if not isinstance(values, list):
        raise ValueError("Embedding must be a list.")

    if len(values) != EMBEDDING_DIMENSIONS:
        raise ValueError("Embedding has an unexpected dimension.")

    if any(type(value) not in (int, float) for value in values):
        raise ValueError("Embedding values must be numbers.")

    vector = [float(value) for value in values]

    if not all(math.isfinite(value) for value in vector):
        raise ValueError("Embedding values must be finite.")

    length = math.hypot(*vector)
    if not math.isfinite(length) or length == 0:
        raise ValueError("Embedding must have a finite, nonzero length.")

    return [value / length for value in vector]
