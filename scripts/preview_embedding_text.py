import argparse

from sqlalchemy import select

from app.database import SessionLocal
from app.embedding_text import build_image_embedding_text
from app.models import Image, Tenant
from app.schemas import VisionMetadata


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preview an image's embedding input text."
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

            stored = image.image_metadata
            metadata = VisionMetadata.model_validate({
                "subject": stored.subject,
                "category": stored.category,
                "attributes": stored.attributes,
                "caption": stored.caption,
                "confidence": stored.confidence,
            })
            text = build_image_embedding_text(metadata)

    except Exception as exc:
        raise SystemExit(
            f"Preview failed: {type(exc).__name__}. "
            "Error details withheld to protect secrets."
        ) from None

    print("Image:", args.external_id)
    print("Embedding input text:")
    print(text)


if __name__ == "__main__":
    main()
