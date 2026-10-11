from time import sleep

from sqlalchemy import select

from app.database import SessionLocal
from app.embedding_text import build_post_embedding_text
from app.embedding_vectors import EMBEDDING_PROFILE
from app.models import Embedding, Post, Tenant
from app.post_embeddings import embed_post
from app.retries import call_with_gemini_retries
from app.schemas import PostCreate


def run_post_embedding_batch(*, sources: list[dict], max_steps: int = 3,
                             pause_seconds: int = 15) -> tuple[int, int]:
    if type(max_steps) is not int or not 1 <= max_steps <= 10:
        raise ValueError("max_steps must be between 1 and 10.")
    if type(pause_seconds) is not int or not 0 <= pause_seconds <= 60:
        raise ValueError("pause_seconds must be between 0 and 60.")
    payloads = [PostCreate(external_id=source["id"], title=source["title"],
                           content=source["content"]) for source in sources]
    post_ids = [payload.external_id for payload in payloads]
    if not post_ids or any(not value.strip() for value in post_ids) or len(set(post_ids)) != len(post_ids):
        raise ValueError("Post IDs must be nonempty and unique.")
    for payload in payloads:
        build_post_embedding_text(title=payload.title, content=payload.content)

    # Persist source posts before the embedding client's separate lookup.
    # Validate all stored text before sending any request or reusing a vector.
    with SessionLocal.begin() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.name == "FlyRank Demo").with_for_update())
        if tenant is None:
            raise LookupError("Demo tenant not found.")
        tenant_id = tenant.id
        for payload in payloads:
            post = db.scalar(select(Post).where(
                Post.tenant_id == tenant_id, Post.external_id == payload.external_id
            ).with_for_update())
            if post is None:
                db.add(Post(tenant_id=tenant_id, **payload.model_dump()))
            elif post.title != payload.title or post.content != payload.content:
                raise ValueError("Saved post differs from the evaluation source.")
        db.flush()
        embedded_ids = set(db.scalars(
            select(Post.external_id).join(Embedding, Embedding.owner_id == Post.id).where(
                Post.tenant_id == tenant_id, Post.external_id.in_(post_ids),
                Embedding.tenant_id == tenant_id, Embedding.owner_type == "post",
                Embedding.model_name == EMBEDDING_PROFILE,
            )
        ).all())

    pending = [external_id for external_id in post_ids if external_id not in embedded_ids]
    selected = pending[:max_steps]
    completed, total = len(embedded_ids), len(post_ids)
    print(f"Saved post embeddings: {completed}/{total}", flush=True)

    def on_retry(next_attempt, http_code):
        print(f"Retrying post: attempt {next_attempt}/3 after HTTP {http_code}", flush=True)

    for step, external_id in enumerate(selected, start=1):
        print(f"Batch step: {step}/{len(selected)} | post={external_id}", flush=True)
        embedding_id, created = call_with_gemini_retries(
            lambda: embed_post(tenant_id=tenant_id, external_id=external_id),
            on_retry=on_retry,
        )
        completed += 1
        print("Embedding ID:", embedding_id)
        print("Result:", "saved" if created else "already exists")
        print(f"Post embeddings: {completed}/{total}", flush=True)
        if step < len(selected) and pause_seconds:
            print(f"Waiting {pause_seconds} seconds.", flush=True)
            sleep(pause_seconds)

    print("All evaluation post embeddings are stored." if completed == total
          else "Batch step limit reached. Rerun to continue.")
    return completed, total
