"""Save a safe read-only audit report. Does not call Gemini."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.data_audit import audit_saved_data
from app.database import engine
from app.vision import VISION_MODEL


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def audit_database(*, database_engine=engine, image_sources, post_sources):
    if database_engine.dialect.name != "postgresql":
        raise ValueError("The live audit requires PostgreSQL read-only transactions.")
    with database_engine.connect().execution_options(
        isolation_level="REPEATABLE READ", postgresql_readonly=True,
    ) as connection:
        with connection.begin():
            with Session(bind=connection, autoflush=False) as db:
                return audit_saved_data(
                    db, image_sources=image_sources, post_sources=post_sources,
                    confidence_threshold=settings.vision_confidence_threshold,
                    vision_model=VISION_MODEL, max_calls=settings.ai_max_calls,
                    budget_usd=settings.ai_budget_usd,
                )


def output_path(value=None):
    root = PROJECT_ROOT.resolve()
    reports = (root / "reports").resolve()
    if not reports.is_relative_to(root):
        raise ValueError("Reports must remain inside the project.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    target = (root / (value or f"reports/saved_data_audit_{stamp}.json")).resolve()
    if not target.is_relative_to(reports) or target.suffix.lower() != ".json":
        raise ValueError("Audit output must be JSON inside reports.")
    if target.exists():
        raise FileExistsError("Audit output already exists.")
    return target


def main():
    parser = argparse.ArgumentParser(description="Audit saved data without database writes or Gemini calls.")
    parser.add_argument("--output", help="New JSON filename inside reports; defaults to a timestamped report.")
    args = parser.parse_args()
    try:
        target = output_path(args.output)
        image_bytes = (PROJECT_ROOT / "data/images.json").read_bytes()
        post_bytes = (PROJECT_ROOT / "data/eval_posts_audited_v1.json").read_bytes()
        report = audit_database(image_sources=json.loads(image_bytes), post_sources=json.loads(post_bytes))
        report["corpus_manifest_sha256"] = hashlib.sha256(image_bytes).hexdigest()
        report["evaluation_dataset_sha256"] = hashlib.sha256(post_bytes).hexdigest()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, allow_nan=False)
            handle.write("\n")
    except Exception as exc:
        raise SystemExit(f"Audit could not finish: {type(exc).__name__}. Error details withheld to protect secrets.") from None

    images, posts, vectors, costs = (report[key] for key in ("images", "posts", "embeddings", "costs"))
    print(f"Valid corpus metadata: {images['schema_valid_metadata']}/{images['expected']}")
    print(f"Matching evaluation post text: {posts['source_text_matches']}/{posts['expected']}")
    print(f"Valid corpus embeddings: {vectors['valid_corpus_images']}/{images['expected']}")
    print(f"Valid evaluation post embeddings: {vectors['valid_evaluation_posts']}/{posts['expected']}")
    print("Low-confidence corpus images:", images["low_confidence_count"])
    print(f"Cost entries with valid structure: {costs['structurally_valid_records']}/{costs['record_count']}")
    print("Calls without reported usage:", costs["calls_without_reported_usage"])
    print("Audit status:", report["status"])
    print(f"Issues: {len(report['errors'])} errors, {len(report['warnings'])} review items")
    print("Read-only audit. No Gemini requests sent.")
    print("Report saved:", target)
    if not report["live_low_confidence_example_present"]:
        print("Live low-confidence acceptance example remains pending.")
    if report["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
