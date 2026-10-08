import argparse
import json
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Tenant
from app.ranking import rank_images_for_post


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preview image ranking for a saved post."
    )
    parser.add_argument("external_id", nargs="?", default="post_001")
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

        ranked = rank_images_for_post(
            tenant_id=tenant_id,
            external_id=args.external_id,
            corpus_ids=corpus_ids,
            top_k=args.top_k,
        )

    except Exception as exc:
        raise SystemExit(
            f"Ranking failed: {type(exc).__name__}. "
            "Error details withheld to protect secrets."
        ) from None

    print("Post:", args.external_id)
    print("Corpus candidates:", len(corpus_ids))
    print("Ranking by cosine similarity:")

    for position, item in enumerate(ranked, start=1):
        print(
            f"{position}. {item.external_id} "
            f"| score={item.similarity_score:.6f} "
            f"| subject={item.subject}"
        )
        print("   Caption:", item.caption)


if __name__ == "__main__":
    main()
