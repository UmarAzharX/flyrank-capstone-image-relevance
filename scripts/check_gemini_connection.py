from google.genai import errors, types

from app.gemini_client import create_gemini_client
from app.vision import VISION_MODEL


def main() -> None:
    try:
        with create_gemini_client() as client:
            client.models.get(
                model=VISION_MODEL,
                config=types.GetModelConfig(
                    http_options=types.HttpOptions(
                        timeout=10000,
                        retry_options=types.HttpRetryOptions(attempts=1),
                    )
                ),
            )
    except errors.APIError as exc:
        raise SystemExit(
            f"Connection check failed: HTTP {exc.code}."
        ) from None
    except Exception as exc:
        raise SystemExit(
            f"Connection check failed: {type(exc).__name__}. "
            "Error details withheld to protect secrets."
        ) from None

    print("PASS: Gemini connection and model lookup succeeded.")


if __name__ == "__main__":
    main()