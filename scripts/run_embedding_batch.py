import argparse
import json
from pathlib import Path
from time import sleep

from google.genai import errors
from sqlalchemy import select

from app.budget import AIUsageLimitError
from app.database import SessionLocal
from app.embedding_vectors import EMBEDDING_PROFILE
from app.image_embeddings import embed_image
from app.models import Embedding, Image, Tenant
from app.retries import call_with_gemini_retries


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Embed a bounded number of remaining corpus images."
    )
    parser.add_argument("--max-steps", type=int, default=3)
    parser.add_argument("--pause-seconds", type=int, default=15)
    args = parser.parse_args()

    if not 1 <= args.max_steps <= 50:
        parser.error("--max-steps must be between 1 and 50.")
    if not 0 <= args.pause_seconds <= 60:
        parser.error("--pause-seconds must be between 0 and 60.")

    try:
        manifest = json.loads(
            (PROJECT_ROOT / "data" / "images.json").read_text(
                encoding="utf-8"
            )
        )
        corpus_ids = [item["id"] for item in manifest]
        if not corpus_ids or len(set(corpus_ids)) != len(corpus_ids):
            raise ValueError("Manifest must contain unique image IDs.")

        with SessionLocal() as db:
            tenant_id = db.scalar(
                select(Tenant.id).where(Tenant.name == "FlyRank Demo")
            )
            if tenant_id is None:
                raise LookupError("Demo tenant not found.")

            images = db.execute(
                select(Image.id, Image.external_id)
                .where(
                    Image.tenant_id == tenant_id,
                    Image.external_id.in_(corpus_ids),
                )
                .order_by(Image.id)
            ).all()

            if len(images) != len(corpus_ids):
                raise ValueError("Some corpus images are not seeded.")

            existing_ids = set(
                db.scalars(
                    select(Embedding.owner_id).where(
                        Embedding.tenant_id == tenant_id,
                        Embedding.owner_type == "image",
                        Embedding.model_name == EMBEDDING_PROFILE,
                        Embedding.owner_id.in_(
                            [image.id for image in images]
                        ),
                    )
                ).all()
            )

        pending = [
            image.external_id
            for image in images
            if image.id not in existing_ids
        ]
        selected = pending[:args.max_steps]
        completed = len(existing_ids)
        total = len(corpus_ids)

        print(f"Saved corpus embeddings: {completed}/{total}")

        def on_retry(next_attempt: int, http_code: int) -> None:
            print(
                f"Retrying: attempt {next_attempt}/3 "
                f"after HTTP {http_code}"
            )

        for step, external_id in enumerate(selected, start=1):
            print(f"Batch step: {step}/{len(selected)}")
            print("Selected image:", external_id)

            embedding_id, created = call_with_gemini_retries(
                lambda: embed_image(
                    tenant_id=tenant_id,
                    external_id=external_id,
                ),
                on_retry=on_retry,
            )

            completed += 1
            print("Embedding ID:", embedding_id)
            print("Result:", "saved" if created else "already exists")
            print(f"Corpus embeddings: {completed}/{total}")

            if step < len(selected) and args.pause_seconds:
                print(f"Waiting {args.pause_seconds} seconds.")
                sleep(args.pause_seconds)

        if completed == total:
            print("All corpus embeddings are stored.")
        else:
            print("Batch step limit reached. Rerun to continue.")

    except AIUsageLimitError as exc:
        raise SystemExit(f"Embedding batch blocked: {exc}") from None
    except errors.APIError as exc:
        raise SystemExit(
            f"Embedding batch stopped: HTTP {exc.code}."
        ) from None
    except Exception as exc:
        raise SystemExit(
            f"Embedding batch stopped: {type(exc).__name__}. "
            "Error details withheld to protect secrets."
        ) from None


if __name__ == "__main__":
    main()
