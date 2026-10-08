import math

from sqlalchemy import select

from app.database import SessionLocal
from app.embedding_client import generate_text_embedding
from app.embedding_text import build_post_embedding_text
from app.embedding_vectors import (
    EMBEDDING_PROFILE,
    validate_and_normalize_vector,
)
from app.models import Embedding, Post


def embed_post(
    *,
    tenant_id: int,
    external_id: str,
) -> tuple[int, bool]:
    with SessionLocal.begin() as db:
        post = db.scalar(
            select(Post)
            .where(
                Post.tenant_id == tenant_id,
                Post.external_id == external_id,
            )
            .with_for_update()
        )
        if post is None:
            raise LookupError("Post not found.")

        existing = db.scalar(
            select(Embedding).where(
                Embedding.tenant_id == tenant_id,
                Embedding.owner_type == "post",
                Embedding.owner_id == post.id,
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

        vector = generate_text_embedding(
            tenant_id=tenant_id,
            owner_type="post",
            owner_id=post.id,
            text=build_post_embedding_text(
                title=post.title,
                content=post.content,
            ),
        )

        embedding = Embedding(
            tenant_id=tenant_id,
            owner_type="post",
            owner_id=post.id,
            model_name=EMBEDDING_PROFILE,
            vector=vector,
        )
        db.add(embedding)
        db.flush()
        embedding_id = embedding.id

    return embedding_id, True
