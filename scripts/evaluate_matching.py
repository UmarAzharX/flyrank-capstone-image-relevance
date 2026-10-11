import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.embedding_vectors import EMBEDDING_PROFILE
from app.mismatch_guard import evaluate_mismatch
from app.models import Post, Tenant
from app.ranking import rank_images_for_post
from app.selection import select_eligible_candidates


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def summarize_results(results: list[dict]) -> dict:
    if not results:
        raise ValueError("Evaluation must contain at least one post.")
    seen = set()
    correct = returned = 0
    for row in results:
        post_id = row["post_id"]
        if post_id in seen:
            raise ValueError("Duplicate evaluation post ID.")
        seen.add(post_id)
        expected = row["expected_image_id"]
        predicted = row["predicted_image_id"]
        if not isinstance(expected, str) or not expected:
            raise ValueError("Expected image ID is required.")
        if predicted is not None:
            if not isinstance(predicted, str) or not predicted:
                raise ValueError("Invalid prediction ID.")
            returned += 1
            correct += int(predicted == expected)
    total = len(results)
    return {
        "post_count": total,
        "returned_count": returned,
        "abstained_count": total - returned,
        "correct_exact_matches": correct,
        "top1_exact_match_all_posts": correct / total,
        "top1_exact_match_returned_posts": correct / returned if returned else None,
        "coverage": returned / total,
    }


def resolve_dataset_path(value: str | Path) -> Path:
    root = PROJECT_ROOT.resolve()
    dataset_path = (root / value).resolve()
    if not dataset_path.is_relative_to(root / "data") or dataset_path.suffix.lower() != ".json":
        raise ValueError("Evaluation dataset must be a JSON file inside the project's data directory.")
    return dataset_path


def evaluate(dataset_path: str | Path = "data/eval_posts.json") -> dict:
    dataset_path = resolve_dataset_path(dataset_path)
    dataset_bytes = dataset_path.read_bytes()
    corpus_bytes = (PROJECT_ROOT / "data" / "images.json").read_bytes()
    dataset = json.loads(dataset_bytes)
    corpus = json.loads(corpus_bytes)
    corpus_ids = {item["id"] for item in corpus}
    post_ids = [item["id"] for item in dataset]
    if not corpus_ids or len(corpus_ids) != len(corpus):
        raise ValueError("Invalid corpus IDs.")
    if not post_ids or len(set(post_ids)) != len(post_ids):
        raise ValueError("Invalid evaluation post IDs.")

    with SessionLocal() as db:
        tenant_id = db.scalar(select(Tenant.id).where(Tenant.name == "FlyRank Demo"))
        if tenant_id is None:
            raise LookupError("Demo tenant not found.")
        posts = db.scalars(
            select(Post).where(Post.tenant_id == tenant_id, Post.external_id.in_(post_ids))
        ).all()
        stored = {post.external_id: (post.title, post.content) for post in posts}

    results = []
    for item in dataset:
        post_id = item["id"]
        title, content = stored[post_id]
        if (title, content) != (item["title"], item["content"]):
            raise ValueError("Stored post text differs from the evaluation dataset.")
        expected_id = item["expected_image_id"]
        if expected_id not in corpus_ids:
            raise ValueError("Expected image is outside the corpus.")

        # Expected labels are used for scoring only, never for ranking or guards.
        ranked = rank_images_for_post(
            tenant_id=tenant_id, external_id=post_id,
            corpus_ids=corpus_ids, top_k=len(corpus_ids),
        )
        guarded = [
            (image, evaluate_mismatch(
                post_title=title, post_content=content,
                image_subject=image.subject, image_caption=image.caption,
                image_attributes=image.attributes, image_confidence=image.confidence,
                confidence_threshold=settings.vision_confidence_threshold,
                similarity_score=image.similarity_score,
                similarity_threshold=settings.similarity_threshold,
            ))
            for image in ranked
        ]
        eligible = select_eligible_candidates(guarded, limit=1)
        predicted_id = eligible[0][0].external_id if eligible else None
        expected_guard = next(guard for image, guard in guarded if image.external_id == expected_id)
        results.append({
            "post_id": post_id,
            "title": title,
            "expected_image_id": expected_id,
            "predicted_image_id": predicted_id,
            "exact_match": predicted_id == expected_id,
            "similarity_score": eligible[0][0].similarity_score if eligible else None,
            "selection_explanation": eligible[0][1].explanation if eligible else "No eligible suggestions.",
            "expected_image_guard": expected_guard.decision,
            "expected_image_explanation": expected_guard.explanation,
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_path": dataset_path.relative_to(PROJECT_ROOT.resolve()).as_posix(),
        "dataset_sha256": hashlib.sha256(dataset_bytes).hexdigest(),
        "corpus_manifest_sha256": hashlib.sha256(corpus_bytes).hexdigest(),
        "embedding_profile": EMBEDDING_PROFILE,
        "vision_confidence_threshold": settings.vision_confidence_threshold,
        "similarity_threshold": settings.similarity_threshold,
        "matching_policy_version": "subject-context-confidence-similarity-v1",
        "evaluation_stage": "Automated guarded top-1 selection before human review",
        "metric_definition": "Exact image-ID match; abstentions count as misses in the all-posts metric.",
        "metrics": summarize_results(results),
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure matching against a versioned evaluation dataset.")
    parser.add_argument("--dataset", default="data/eval_posts.json")
    parser.add_argument("--output", default="reports/evaluation_baseline.json")
    args = parser.parse_args()
    try:
        output = (PROJECT_ROOT / args.output).resolve()
        if not output.is_relative_to(PROJECT_ROOT):
            raise ValueError("Report must stay inside the project.")
        if output.exists():
            raise FileExistsError()
        report = evaluate(args.dataset)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
    except FileExistsError:
        raise SystemExit("Report already exists. Use --output with a new filename to preserve it.") from None
    except Exception as exc:
        raise SystemExit(
            f"Evaluation failed: {type(exc).__name__}. Details withheld to protect secrets."
        ) from None

    for row in report["results"]:
        predicted = row["predicted_image_id"] or "none"
        outcome = "match" if row["exact_match"] else "miss"
        print(f"{row['post_id']} | expected={row['expected_image_id']} | predicted={predicted} | {outcome}")
    print("Dataset:", report["dataset_path"])
    metrics = report["metrics"]
    print(f"Top-1 exact matches, all posts: {metrics['correct_exact_matches']}/{metrics['post_count']} ({metrics['top1_exact_match_all_posts']:.1%})")
    print(f"Coverage: {metrics['returned_count']}/{metrics['post_count']} ({metrics['coverage']:.1%})")
    conditional = metrics["top1_exact_match_returned_posts"]
    print("Exact-match rate among returned results:", f"{conditional:.1%}" if conditional is not None else "not applicable")
    print("Report saved:", output)


if __name__ == "__main__":
    main()
