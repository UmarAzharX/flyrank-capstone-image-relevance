import argparse
import json
import subprocess
import sys
from pathlib import Path
from time import sleep

from sqlalchemy import select

from app.database import SessionLocal
from app.embedding_vectors import EMBEDDING_PROFILE
from app.models import Embedding, Post, Tenant


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Embed remaining evaluation posts."
    )
    parser.add_argument("--max-steps", type=int, default=3)
    parser.add_argument("--pause-seconds", type=int, default=15)
    args = parser.parse_args()

    if not 1 <= args.max_steps <= 10:
        parser.error("--max-steps must be between 1 and 10.")
    if not 0 <= args.pause_seconds <= 60:
        parser.error("--pause-seconds must be between 0 and 60.")

    try:
        manifest = json.loads(
            (PROJECT_ROOT / "data" / "eval_posts.json").read_text(
                encoding="utf-8"
            )
        )
        post_ids = [item["id"] for item in manifest]
        if not post_ids or len(set(post_ids)) != len(post_ids):
            raise ValueError("Post IDs must be nonempty and unique.")

        with SessionLocal() as db:
            tenant_id = db.scalar(
                select(Tenant.id).where(Tenant.name == "FlyRank Demo")
            )
            if tenant_id is None:
                raise LookupError("Demo tenant not found.")

            embedded_ids = set(
                db.scalars(
                    select(Post.external_id)
                    .join(Embedding, Embedding.owner_id == Post.id)
                    .where(
                        Post.tenant_id == tenant_id,
                        Post.external_id.in_(post_ids),
                        Embedding.tenant_id == tenant_id,
                        Embedding.owner_type == "post",
                        Embedding.model_name == EMBEDDING_PROFILE,
                    )
                ).all()
            )

        pending = [
            external_id
            for external_id in post_ids
            if external_id not in embedded_ids
        ]
        selected = pending[:args.max_steps]
        completed = len(embedded_ids)
        total = len(post_ids)

        print(f"Saved post embeddings: {completed}/{total}", flush=True)

        for step, external_id in enumerate(selected, start=1):
            print(
                f"Batch step: {step}/{len(selected)} "
                f"| post={external_id}",
                flush=True,
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "scripts.embed_one_post",
                    external_id,
                ],
                cwd=PROJECT_ROOT,
                check=False,
            )
            if result.returncode != 0:
                raise SystemExit(
                    f"Batch stopped at {external_id}. "
                    "Rerun to continue after resolving the error."
                )

            completed += 1
            print(
                f"Post embeddings: {completed}/{total}",
                flush=True,
            )

            if step < len(selected) and args.pause_seconds:
                print(
                    f"Waiting {args.pause_seconds} seconds.",
                    flush=True,
                )
                sleep(args.pause_seconds)

        if completed == total:
            print("All evaluation post embeddings are stored.")
        else:
            print("Batch step limit reached. Rerun to continue.")

    except KeyboardInterrupt:
        raise SystemExit("Batch interrupted. Rerun to continue.") from None
    except Exception as exc:
        raise SystemExit(
            f"Post batch failed: {type(exc).__name__}. "
            "Error details withheld to protect secrets."
        ) from None


if __name__ == "__main__":
    main()
