import argparse
import json
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.mismatch_guard import evaluate_mismatch
from app.models import Post, Tenant
from app.ranking import rank_images_for_post


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preview image rankings with subject decisions."
    )
    parser.add_argument("external_id", nargs="?", default="post_003")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    try:
        manifest = json.loads(
            (PROJECT_ROOT / "data" / "images.json").read_text(
                encoding="utf-8"
            )
        )
        corpus_ids = {item["id"] for item in manifest}
        if len(corpus_ids) != len(manifest):
            raise ValueError("Duplicate corpus IDs found.")

        with SessionLocal() as db:
            tenant_id = db.scalar(
                select(Tenant.id).where(Tenant.name == "FlyRank Demo")
            )
            if tenant_id is None:
                raise LookupError("Demo tenant not found.")

            post = db.scalar(
                select(Post).where(
                    Post.tenant_id == tenant_id,
                    Post.external_id == args.external_id,
                )
            )
            if post is None:
                raise LookupError("Post not found.")

            title = post.title
            content = post.content

        ranked = rank_images_for_post(
            tenant_id=tenant_id,
            external_id=args.external_id,
            corpus_ids=corpus_ids,
            top_k=args.top_k,
        )

        guarded = [
            (
                item,
                evaluate_mismatch(
                    post_title=title,
                    post_content=content,
                    image_subject=item.subject,
                    image_caption=item.caption,
                    image_attributes=item.attributes,
                ),
            )
            for item in ranked
        ]

    except Exception as exc:
        raise SystemExit(
            f"Guarded ranking failed: {type(exc).__name__}. "
            "Error details withheld to protect secrets."
        ) from None

    print("Post:", args.external_id)
    print("Title:", title)
    print("Corpus candidates:", len(corpus_ids))

    for position, (item, guard) in enumerate(guarded, start=1):
        print(
            f"{position}. {item.external_id} "
            f"| score={item.similarity_score:.6f} "
            f"| guard={guard.decision}"
        )
        print("   Explanation:", guard.explanation)
        print("   Caption:", item.caption)


if __name__ == "__main__":
    main()
