from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import SessionLocal
from app.embedding_vectors import EMBEDDING_PROFILE
from app.models import Embedding, Image, Post
from app.similarity import cosine_similarity


@dataclass(frozen=True)
class RankedImage:
    image_id: int
    external_id: str
    subject: str
    caption: str
    attributes: list[str]
    similarity_score: float


def rank_images_for_post(
    *,
    tenant_id: int,
    external_id: str,
    corpus_ids: set[str],
    top_k: int = 5,
) -> list[RankedImage]:
    if not corpus_ids or not 1 <= top_k <= len(corpus_ids):
        raise ValueError("Invalid corpus or result count.")

    with SessionLocal() as db:
        post = db.scalar(
            select(Post).where(
                Post.tenant_id == tenant_id,
                Post.external_id == external_id,
            )
        )
        if post is None:
            raise LookupError("Post not found.")

        post_embedding = db.scalars(
            select(Embedding).where(
                Embedding.tenant_id == tenant_id,
                Embedding.owner_type == "post",
                Embedding.owner_id == post.id,
                Embedding.model_name == EMBEDDING_PROFILE,
            )
        ).one_or_none()
        if post_embedding is None:
            raise LookupError("Post embedding not found.")

        images = db.scalars(
            select(Image)
            .options(selectinload(Image.image_metadata))
            .where(
                Image.tenant_id == tenant_id,
                Image.external_id.in_(corpus_ids),
            )
        ).all()
        if len(images) != len(corpus_ids):
            raise ValueError("Some corpus images are not seeded.")

        embeddings = db.scalars(
            select(Embedding).where(
                Embedding.tenant_id == tenant_id,
                Embedding.owner_type == "image",
                Embedding.owner_id.in_([image.id for image in images]),
                Embedding.model_name == EMBEDDING_PROFILE,
            )
        ).all()
        by_image = {
            embedding.owner_id: embedding
            for embedding in embeddings
        }
        if len(by_image) != len(embeddings):
            raise ValueError("Duplicate image embeddings found.")

        ranked = []
        for image in images:
            embedding = by_image.get(image.id)
            metadata = image.image_metadata
            if embedding is None or metadata is None:
                raise LookupError(
                    "A corpus image is missing its embedding or metadata."
                )

            ranked.append(
                RankedImage(
                    image_id=image.id,
                    external_id=image.external_id,
                    subject=metadata.subject,
                    caption=metadata.caption,
                    attributes=list(metadata.attributes),
                    similarity_score=cosine_similarity(
                        post_embedding.vector,
                        embedding.vector,
                    ),
                )
            )

    ranked.sort(
        key=lambda item: (-item.similarity_score, item.external_id)
    )
    return ranked[:top_k]
