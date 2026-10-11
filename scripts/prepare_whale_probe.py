"""Prepare a separate whale post using the existing embedding and budget path."""

import json
import math
from pathlib import Path

from google.genai import errors
from sqlalchemy import select

from app.budget import AIUsageLimitError
from app.database import SessionLocal
from app.embedding_text import build_post_embedding_text
from app.embedding_vectors import EMBEDDING_PROFILE, validate_and_normalize_vector
from app.models import Embedding, Post, Tenant
from app.post_embeddings import embed_post
from app.schemas import PostCreate


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROBE_ID = "acceptance_whale_v1"


def prepare_probe(case):
    if case["id"] != "guard_003" or case["case_type"] != "no_suitable_image":
        raise ValueError("Expected the designated whale case.")
    payload = PostCreate(external_id=PROBE_ID, title=case["post_title"], content=case["post_content"])
    build_post_embedding_text(title=payload.title, content=payload.content)
    with SessionLocal.begin() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.name == "FlyRank Demo").with_for_update())
        if tenant is None:
            raise LookupError("Demo tenant not found.")
        post = db.scalar(select(Post).where(
            Post.tenant_id == tenant.id, Post.external_id == PROBE_ID,
        ).with_for_update())
        if post is None:
            post = Post(tenant_id=tenant.id, **payload.model_dump())
            db.add(post)
            db.flush()
        elif (post.title, post.content) != (payload.title, payload.content):
            raise ValueError("Stored probe text differs; cached embedding must not be reused.")
        tenant_id, post_id = tenant.id, post.id
    embedding_id, created = embed_post(tenant_id=tenant_id, external_id=PROBE_ID)
    with SessionLocal() as db:
        embedding = db.scalar(select(Embedding).where(
            Embedding.id == embedding_id, Embedding.tenant_id == tenant_id,
            Embedding.owner_type == "post", Embedding.owner_id == post_id,
            Embedding.model_name == EMBEDDING_PROFILE,
        ))
        if embedding is None:
            raise LookupError("Saved probe embedding not found.")
        validate_and_normalize_vector(embedding.vector)
        length = math.hypot(*embedding.vector)
        if not math.isclose(length, 1.0, rel_tol=1e-6, abs_tol=1e-6):
            raise ValueError("Saved probe embedding is not normalized.")
        dimensions = len(embedding.vector)
    return post_id, embedding_id, created, dimensions, length


def main():
    try:
        cases = json.loads((PROJECT_ROOT / "data/guard_cases.json").read_text(encoding="utf-8-sig"))
        matches = [case for case in cases if case["id"] == "guard_003"]
        if len(matches) != 1:
            raise ValueError("Expected exactly one whale case.")
        post_id, embedding_id, created, dimensions, length = prepare_probe(matches[0])
    except AIUsageLimitError:
        raise SystemExit("Whale embedding blocked by the configured call or budget limit.") from None
    except errors.APIError as exc:
        raise SystemExit(f"Whale embedding request failed: HTTP {exc.code}. No automatic retry.") from None
    except Exception as exc:
        raise SystemExit(f"Whale preparation failed: {type(exc).__name__}. Error details withheld to protect secrets.") from None
    print("Whale embedding saved." if created else "Whale embedding reused. No Gemini request sent.")
    print("Post external ID:", PROBE_ID)
    print("Post database ID:", post_id)
    print("Embedding ID:", embedding_id)
    print("Configuration:", EMBEDDING_PROFILE)
    print("Dimensions:", dimensions)
    print("Vector length:", f"{length:.6f}")
    print("Next API request: POST", f"http://127.0.0.1:8000/posts/{post_id}/suggestions?top_k=5")
    print("The API no-match check has not been run yet.")
    print("This probe is outside the ten-post evaluation. No evaluation files were changed.")


if __name__ == "__main__":
    main()
