import argparse
import json
import math
from pathlib import Path

from google.genai import errors
from sqlalchemy import select

from app.budget import AIUsageLimitError
from app.database import SessionLocal
from app.embedding_text import build_post_embedding_text
from app.embedding_vectors import validate_and_normalize_vector
from app.models import Embedding, Post, Tenant
from app.post_embeddings import embed_post
from app.schemas import PostCreate


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Save and embed one evaluation post."
    )
    parser.add_argument("external_id", nargs="?", default="post_001")
    args = parser.parse_args()

    try:
        posts = json.loads(
            (PROJECT_ROOT / "data" / "eval_posts.json").read_text(
                encoding="utf-8"
            )
        )
        matches = [
            post for post in posts if post["id"] == args.external_id
        ]
        if len(matches) != 1:
            raise ValueError("Expected exactly one matching post.")

        source = matches[0]
        payload = PostCreate(
            external_id=source["id"],
            title=source["title"],
            content=source["content"],
        )
        build_post_embedding_text(
            title=payload.title,
            content=payload.content,
        )

        # Save the post before the embedding client looks it up.
        with SessionLocal.begin() as db:
            tenant = db.scalar(
                select(Tenant)
                .where(Tenant.name == "FlyRank Demo")
                .with_for_update()
            )
            if tenant is None:
                raise LookupError("Demo tenant not found.")
            tenant_id = tenant.id

            post = db.scalar(
                select(Post)
                .where(
                    Post.tenant_id == tenant_id,
                    Post.external_id == payload.external_id,
                )
                .with_for_update()
            )
            if post is None:
                db.add(
                    Post(
                        tenant_id=tenant_id,
                        **payload.model_dump(),
                    )
                )
            elif (
                post.title != payload.title
                or post.content != payload.content
            ):
                raise ValueError(
                    "Saved post differs from the evaluation source."
                )

        embedding_id, created = embed_post(
            tenant_id=tenant_id,
            external_id=args.external_id,
        )

        with SessionLocal() as db:
            stored = db.scalar(
                select(Embedding).where(
                    Embedding.id == embedding_id,
                    Embedding.tenant_id == tenant_id,
                    Embedding.owner_type == "post",
                )
            )
            if stored is None:
                raise LookupError("Saved post embedding not found.")

            validate_and_normalize_vector(stored.vector)
            length = math.hypot(*stored.vector)
            if not math.isclose(
                length, 1.0, rel_tol=1e-6, abs_tol=1e-6
            ):
                raise ValueError("Saved embedding is not normalized.")

            profile = stored.model_name
            dimensions = len(stored.vector)

    except AIUsageLimitError as exc:
        raise SystemExit(f"Embedding request blocked: {exc}") from None
    except errors.APIError as exc:
        raise SystemExit(
            f"Embedding request failed: HTTP {exc.code}."
        ) from None
    except Exception as exc:
        raise SystemExit(
            f"Post embedding failed: {type(exc).__name__}. "
            "Error details withheld to protect secrets."
        ) from None

    if created:
        print("Post embedding saved and read back from PostgreSQL.")
    else:
        print("Post embedding already exists. No Gemini request sent.")

    print("Post:", args.external_id)
    print("Embedding ID:", embedding_id)
    print("Configuration:", profile)
    print("Dimensions:", dimensions)
    print("Vector length:", f"{length:.6f}")


if __name__ == "__main__":
    main()
