import argparse
import math

from google.genai import errors
from sqlalchemy import select

from app.budget import AIUsageLimitError
from app.database import SessionLocal
from app.embedding_client import generate_text_embedding
from app.embedding_text import build_image_embedding_text
from app.embedding_vectors import EMBEDDING_MODEL
from app.models import Image, Tenant
from app.schemas import VisionMetadata


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate and validate one image-description embedding."
    )
    parser.add_argument("external_id", nargs="?", default="fox_001")
    args = parser.parse_args()

    try:
        with SessionLocal() as db:
            image = db.scalar(
                select(Image)
                .join(Tenant)
                .where(
                    Tenant.name == "FlyRank Demo",
                    Image.external_id == args.external_id,
                )
            )
            if image is None or image.image_metadata is None:
                raise LookupError("Image or vision metadata not found.")

            tenant_id = image.tenant_id
            image_id = image.id
            stored = image.image_metadata
            metadata = VisionMetadata.model_validate({
                "subject": stored.subject,
                "category": stored.category,
                "attributes": stored.attributes,
                "caption": stored.caption,
                "confidence": stored.confidence,
            })
            text = build_image_embedding_text(metadata)

        vector = generate_text_embedding(
            tenant_id=tenant_id,
            owner_type="image",
            owner_id=image_id,
            text=text,
            title=metadata.subject,
        )

    except AIUsageLimitError as exc:
        raise SystemExit(f"Embedding request blocked: {exc}") from None
    except errors.APIError as exc:
        raise SystemExit(
            f"Embedding request failed: HTTP {exc.code}."
        ) from None
    except Exception as exc:
        raise SystemExit(
            f"Embedding test failed: {type(exc).__name__}. "
            "Error details withheld to protect secrets."
        ) from None

    print("Image:", args.external_id)
    print("Model:", EMBEDDING_MODEL)
    print("Dimensions:", len(vector))
    print("Vector length:", f"{math.hypot(*vector):.6f}")
    print("First five values:", [round(value, 6) for value in vector[:5]])
    print("Embedding passed validation.")


if __name__ == "__main__":
    main()
