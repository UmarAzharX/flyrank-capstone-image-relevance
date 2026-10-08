from collections.abc import Callable
from time import sleep
from typing import TypeVar

from google.genai import errors

T = TypeVar("T")
RETRYABLE_CODES = {429, 500, 502, 503, 504}


def call_with_gemini_retries(
    operation: Callable[[], T],
    *,
    on_retry: Callable[[int, int], None] | None = None,
    max_attempts: int = 3,
) -> T:
    if not 1 <= max_attempts <= 5:
        raise ValueError("max_attempts must be between 1 and 5.")

    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except errors.APIError as exc:
            if exc.code not in RETRYABLE_CODES or attempt == max_attempts:
                raise

            sleep(2**attempt)

            if on_retry is not None:
                on_retry(attempt + 1, exc.code)

    raise RuntimeError("Retry loop ended unexpectedly.")