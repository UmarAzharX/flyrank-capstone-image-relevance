import math

from sqlalchemy import select

from app.database import SessionLocal
from app.embedding_client import generate_text_embedding
from app.embedding_text import build_image_embedding_text
from app.embedding_vectors import (
    EMBEDDING_PROFILE,
    validate_and_normalize_vector,
)
from app.models import Embedding, Image
from app.schemas import VisionMetadata


def embed_image(
    *,
    tenant_id: int,
    external_id: str,
    job_id: int | None = None,
) -> tuple[int, bool]:
    with SessionLocal.begin() as db:
        image = db.scalar(
            select(Image)
            .where(
                Image.tenant_id == tenant_id,
                Image.external_id == external_id,
            )
            .with_for_update()
        )
        if image is None or image.image_metadata is None:
            raise LookupError("Image or vision metadata not found.")

        existing = db.scalar(
            select(Embedding).where(
                Embedding.tenant_id == tenant_id,
                Embedding.owner_type == "image",
                Embedding.owner_id == image.id,
                Embedding.model_name == EMBEDDING_PROFILE,
            )
        )
        if existing is not None:
            validate_and_normalize_vector(existing.vector)
            if not math.isclose(
                math.hypot(*existing.vector),
                1.0,
                rel_tol=1e-6,
                abs_tol=1e-6,
            ):
                raise ValueError("Stored embedding is not normalized.")
            return existing.id, False

        stored = image.image_metadata
        metadata = VisionMetadata.model_validate({
            "subject": stored.subject,
            "category": stored.category,
            "attributes": stored.attributes,
            "caption": stored.caption,
            "confidence": stored.confidence,
        })

        vector = generate_text_embedding(
            tenant_id=tenant_id,
            owner_type="image",
            owner_id=image.id,
            **({"job_id": job_id} if job_id is not None else {}),
            text=build_image_embedding_text(metadata),
            title=metadata.subject,
        )

        embedding = Embedding(
            tenant_id=tenant_id,
            owner_type="image",
            owner_id=image.id,
            model_name=EMBEDDING_PROFILE,
            vector=vector,
        )
        db.add(embedding)
        db.flush()
        embedding_id = embedding.id

    return embedding_id, True
