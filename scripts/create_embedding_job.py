from sqlalchemy import select

from app.database import SessionLocal
from app.embedding_jobs import create_or_get_embedding_job, load_embedding_scope
from app.models import Tenant


def main():
    try:
        image_ids, post_sources = load_embedding_scope()
        with SessionLocal() as db:
            tenant_id = db.scalar(select(Tenant.id).where(Tenant.name == "FlyRank Demo"))
            if tenant_id is None:
                raise LookupError("Demo tenant not found.")
        result = create_or_get_embedding_job(tenant_id=tenant_id, image_ids=image_ids,
                                            post_sources=post_sources)
    except Exception as exc:
        raise SystemExit(f"Embedding job creation failed: {type(exc).__name__}. Error details withheld to protect secrets.") from None
    print("Embedding job saved:" if result.created else "Embedding job reused:", result.job_id)
    print("Status:", result.status)
    print("Progress:", f"{result.progress}%")
    print(f"Corpus image embeddings: {result.snapshot.image_completed}/{result.snapshot.image_total}")
    print(f"Evaluation post embeddings: {result.snapshot.post_completed}/{result.snapshot.post_total}")
    print("Remaining embeddings:", len(result.snapshot.pending))
    print("No Gemini requests sent.")
    if result.status == "pending":
        print("Job recorded; background worker has not been started.")


if __name__ == "__main__":
    main()
