import argparse

from google.genai import errors
from pydantic import ValidationError
from sqlalchemy import select

from app.database import SessionLocal
from app.image_processing import process_image
from app.models import Image, Tenant


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Process one image for the demo tenant."
    )
    parser.add_argument(
        "external_id",
        help="Image identifier, such as fox_002",
    )
    args = parser.parse_args()

    try:
        with SessionLocal() as db:
            tenant = db.scalar(
                select(Tenant).where(Tenant.name == "FlyRank Demo")
            )

            if tenant is None:
                raise SystemExit("Demo tenant not found.")
            tenant_id = tenant.id

        image_id = process_image(
            tenant_id=tenant_id,
            external_id=args.external_id,
        )
        if image_id is None:
            print("Metadata already exists. No Gemini request sent.")
            return

        # Use a new session to verify the committed result.
        with SessionLocal() as db:
            saved_image = db.get(Image, image_id)
            saved_metadata = saved_image.image_metadata

            print("Metadata saved and read back from PostgreSQL.")
            print("Image ID:", saved_image.id)
            print("Status:", saved_image.processing_status)
            print("Subject:", saved_metadata.subject)
            print("Confidence:", saved_metadata.confidence)
            print("Low confidence:", saved_metadata.low_confidence)

    except errors.APIError as exc:
        raise SystemExit(
            f"Gemini request failed: HTTP {exc.code}. Nothing saved."
        ) from None
    except ValidationError:
        raise SystemExit(
            "Metadata failed validation. No image metadata saved; "
            "any committed cost record remains."
        ) from None
    except Exception as exc:
        raise SystemExit(
            f"Processing failed: {type(exc).__name__}. "
            "Error details withheld to protect secrets."
        ) from None


if __name__ == "__main__":
    main()