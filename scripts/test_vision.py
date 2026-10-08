from pathlib import Path

from google.genai import errors
from pydantic import ValidationError
from sqlalchemy import select

from app.budget import AIUsageLimitError
from app.cost_tracking import (
    finish_free_tier_vision_call,
    reserve_free_tier_vision_call,
)
from app.database import SessionLocal
from app.models import Image, Tenant
from app.vision import VISION_MODEL, analyze_image


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    image_path = project_root / "data" / "images" / "fox_001.jpg"

    try:
        if not image_path.is_file():
            raise ValueError("Local test image not found.")

        with SessionLocal() as db:
            image = db.scalar(
                select(Image)
                .join(Tenant)
                .where(
                    Tenant.name == "FlyRank Demo",
                    Image.external_id == "fox_001",
                )
            )
            if image is None:
                raise ValueError("Demo fox image record not found.")

            tenant_id = image.tenant_id
            image_id = image.id

        record_id = reserve_free_tier_vision_call(
            tenant_id=tenant_id,
            image_id=image_id,
            model=VISION_MODEL,
        )
        print("Call slot reserved:", record_id)

        def show_usage(
            model: str,
            usage: dict[str, object] | None,
        ) -> None:
            if model != VISION_MODEL:
                raise ValueError("Response model does not match reservation.")

            finish_free_tier_vision_call(
                tenant_id=tenant_id,
                record_id=record_id,
                usage=usage,
            )
            print("Model:", model)
            print("Token usage:", usage)
            print("Cost record updated:", record_id)
            print("Cost USD: 0.00 (free tier)")

        try:
            metadata = analyze_image(image_path, on_usage=show_usage)
        except errors.APIError as exc:
            show_usage(
                VISION_MODEL,
                {
                    "usage_available": False,
                    "call_outcome": "api_error",
                    "http_status": exc.code,
                },
            )
            raise

    except AIUsageLimitError as exc:
        raise SystemExit(f"Gemini request blocked: {exc}") from None
    except errors.APIError as exc:
        raise SystemExit(
            f"Gemini request failed: HTTP {exc.code}. "
            "No metadata accepted."
        ) from None
    except ValidationError:
        raise SystemExit(
            "Gemini output failed schema validation. No metadata accepted."
        ) from None
    except Exception as exc:
        raise SystemExit(
            f"Test failed: {type(exc).__name__}. "
            "Error details withheld to protect secrets."
        ) from None

    print("Gemini request succeeded; metadata passed validation.")
    print(metadata.model_dump_json(indent=2))


if __name__ == "__main__":
    main()