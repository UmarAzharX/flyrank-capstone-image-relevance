import argparse
import json
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Image, Suggestion, Tenant
from app.suggestion_processing import save_post_suggestions


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate and save eligible post suggestions."
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

        saved_ids, created_count = save_post_suggestions(
            tenant_id=tenant_id,
            external_id=args.external_id,
            corpus_ids=corpus_ids,
            limit=args.top_k,
        )

        with SessionLocal() as db:
            rows = db.execute(
                select(
                    Suggestion.id,
                    Image.external_id,
                    Suggestion.similarity_score,
                    Suggestion.guard_decision,
                    Suggestion.explanation,
                )
                .join(Image, Image.id == Suggestion.image_id)
                .where(
                    Suggestion.tenant_id == tenant_id,
                    Image.tenant_id == tenant_id,
                    Suggestion.id.in_(saved_ids),
                )
                .order_by(
                    Suggestion.similarity_score.desc(),
                    Image.external_id,
                )
            ).all()

            if len(rows) != len(saved_ids):
                raise LookupError("Some saved suggestions were not found.")
            if any(row.guard_decision != "pass" for row in rows):
                raise ValueError("A saved suggestion did not pass the guard.")

    except Exception as exc:
        raise SystemExit(
            f"Suggestion processing failed: {type(exc).__name__}. "
            "Error details withheld to protect secrets."
        ) from None

    print("Post:", args.external_id)
    print("Created suggestions:", created_count)
    print("Reused suggestions:", len(saved_ids) - created_count)

    if not rows:
        print("No eligible suggestions to save.")
        return

    print("Suggestions saved and read back from PostgreSQL.")
    for row in rows:
        print(
            f"Suggestion ID: {row.id} "
            f"| image={row.external_id} "
            f"| score={row.similarity_score:.6f} "
            f"| guard={row.guard_decision}"
        )
        print("Explanation:", row.explanation)


if __name__ == "__main__":
    main()
