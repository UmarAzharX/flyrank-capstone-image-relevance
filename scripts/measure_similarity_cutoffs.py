import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.embedding_vectors import EMBEDDING_PROFILE
from app.mismatch_guard import evaluate_mismatch
from app.models import Post, Tenant
from app.ranking import rank_images_for_post
from app.selection import select_eligible_candidates
from app.subject_guard import evaluate_subject_match
from scripts.evaluate_matching import resolve_dataset_path, summarize_results


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CUTOFFS = (0.50, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90)


def pair_counts(pairs: list[dict], cutoff: float) -> dict:
    if type(cutoff) not in (int, float) or not math.isfinite(cutoff) or not -1 <= cutoff <= 1:
        raise ValueError("Invalid similarity cutoff.")
    positive = negative = kept_positive = kept_negative = 0
    seen = set()
    for pair in pairs:
        key = (pair["post_id"], pair["image_id"])
        if key in seen:
            raise ValueError("Duplicate labelled pair.")
        seen.add(key)
        score = pair["similarity_score"]
        label = pair["relevant"]
        if type(score) not in (int, float) or not math.isfinite(score) or not -1 <= score <= 1 or type(label) is not bool:
            raise ValueError("Invalid labelled pair.")
        kept = score >= cutoff
        if label:
            positive += 1
            kept_positive += int(kept)
        else:
            negative += 1
            kept_negative += int(kept)
    if not positive or not negative:
        raise ValueError("Both positive and negative pairs are required.")
    return {
        "reference_pair_count": positive,
        "reference_pairs_above_cutoff": kept_positive,
        "negative_pair_count": negative,
        "negative_pairs_above_cutoff": kept_negative,
    }


def measure(dataset_path: str, negative_path: str) -> dict:
    dataset_file = resolve_dataset_path(dataset_path)
    negative_file = resolve_dataset_path(negative_path)
    dataset_bytes = dataset_file.read_bytes()
    negative_bytes = negative_file.read_bytes()
    corpus_bytes = (PROJECT_ROOT / "data/images.json").read_bytes()
    dataset = json.loads(dataset_bytes)
    negatives = json.loads(negative_bytes)
    corpus = json.loads(corpus_bytes)
    corpus_ids = {row["id"] for row in corpus}
    post_ids = {row["id"] for row in dataset}
    negative_pairs = negatives["pairs"]
    negative_by_post = {row["post_id"]: row for row in negative_pairs}
    if (not dataset or len(post_ids) != len(dataset) or len(corpus_ids) != len(corpus)
            or len(negative_by_post) != len(negative_pairs) or set(negative_by_post) != post_ids):
        raise ValueError("Invalid dataset IDs or negative-pair coverage.")
    with SessionLocal() as db:
        tenant_id = db.scalar(select(Tenant.id).where(Tenant.name == "FlyRank Demo"))
        if tenant_id is None:
            raise LookupError("Demo tenant not found.")
        posts = db.scalars(select(Post).where(Post.tenant_id == tenant_id, Post.external_id.in_(post_ids))).all()
        stored = {post.external_id: (post.title, post.content) for post in posts}

    pairs = []
    guarded_by_post = {}
    for item in dataset:
        post_id = item["id"]
        title, content = stored[post_id]
        if (title, content) != (item["title"], item["content"]):
            raise ValueError("Stored post text differs from dataset.")
        expected = item["expected_image_id"]
        negative = negative_by_post[post_id]
        wrong_id = negative["image_id"]
        if expected == wrong_id or expected not in corpus_ids or wrong_id not in corpus_ids:
            raise ValueError("Invalid reference or negative image ID.")
        ranked = rank_images_for_post(tenant_id=tenant_id, external_id=post_id, corpus_ids=corpus_ids, top_k=len(corpus_ids))
        by_id = {image.external_id: image for image in ranked}
        # Cross-check the documented mismatch; these labels are not inferred
        # from score or from non-reference IDs.
        subject_check = evaluate_subject_match(post_title=title, post_content=content, image_subject=by_id[wrong_id].subject)
        if subject_check.decision != "reject":
            raise ValueError("Negative pair no longer has a confirmed subject mismatch.")
        for image_id, relevant, reason in (
            (expected, True, "Audited dataset reference; known policy/metadata limitations remain."),
            (wrong_id, False, negative["reason"]),
        ):
            image = by_id[image_id]
            pairs.append({"post_id": post_id, "image_id": image_id, "relevant": relevant, "similarity_score": image.similarity_score, "reason": reason})
        guarded_by_post[post_id] = [
            (image, evaluate_mismatch(
                post_title=title, post_content=content,
                image_subject=image.subject, image_caption=image.caption,
                image_attributes=image.attributes, image_confidence=image.confidence,
                confidence_threshold=settings.vision_confidence_threshold,
                similarity_score=image.similarity_score,
                similarity_threshold=-1.0,
            )) for image in ranked
        ]

    sweep = []
    baseline_eligible = [
        (post_id, image) for post_id, candidates in guarded_by_post.items()
        for image, guard in candidates if guard.decision == "pass"
    ]
    for cutoff in CUTOFFS:
        results = []
        for item in dataset:
            eligible = select_eligible_candidates([
                pair for pair in guarded_by_post[item["id"]]
                if pair[0].similarity_score >= cutoff
            ], limit=1)
            predicted = eligible[0][0].external_id if eligible else None
            results.append({"post_id": item["id"], "expected_image_id": item["expected_image_id"], "predicted_image_id": predicted})
        sweep.append({
            "cutoff": cutoff, **pair_counts(pairs, cutoff),
            "baseline_guard_pass_candidate_count": len(baseline_eligible),
            "guard_pass_candidates_above_cutoff": sum(image.similarity_score >= cutoff for _, image in baseline_eligible),
            "guard_pass_candidates_removed": [
                {"post_id": post_id, "image_id": image.external_id, "similarity_score": image.similarity_score}
                for post_id, image in baseline_eligible if image.similarity_score < cutoff
            ],
            "guarded_top1_metrics": summarize_results(results), "predictions": results,
        })
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_path": dataset_file.relative_to(PROJECT_ROOT.resolve()).as_posix(),
        "dataset_sha256": hashlib.sha256(dataset_bytes).hexdigest(),
        "negative_pairs_sha256": hashlib.sha256(negative_bytes).hexdigest(),
        "negative_pair_label_method": negatives["label_method"],
        "corpus_manifest_sha256": hashlib.sha256(corpus_bytes).hexdigest(),
        "embedding_profile": EMBEDDING_PROFILE,
        "vision_confidence_threshold": settings.vision_confidence_threshold,
        "diagnostic_base_similarity_threshold": -1.0,
        "study_scope": "Development-set diagnostics: 10 reference pairs and 10 subject-mismatch pairs; same-subject/context negatives are not covered. No live policy changes.",
        "pairs": pairs,
        "sweep": sweep,
    }


def main():
    parser = argparse.ArgumentParser(description="Measure candidate cosine cutoffs without changing matching policy.")
    parser.add_argument("--dataset", default="data/eval_posts_audited_v1.json")
    parser.add_argument("--negative-pairs", default="data/similarity_negative_pairs_v1.json")
    parser.add_argument("--output", default="reports/similarity_cutoff_study_v1.json")
    args = parser.parse_args()
    try:
        output = (PROJECT_ROOT / args.output).resolve()
        if not output.is_relative_to(PROJECT_ROOT.resolve()) or output.suffix.lower() != ".json":
            raise ValueError("Report must be a JSON file inside project.")
        if output.exists():
            raise FileExistsError()
        report = measure(args.dataset, args.negative_pairs)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, allow_nan=False)
            handle.write("\n")
    except FileExistsError:
        raise SystemExit("Report already exists. Use --output with a new filename.") from None
    except Exception as exc:
        raise SystemExit(f"Cutoff study failed: {type(exc).__name__}. Details withheld to protect secrets.") from None
    for row in report["pairs"]:
        label = "reference" if row["relevant"] else "wrong subject"
        print(f"{row['post_id']} | {label}={row['image_id']} | score={row['similarity_score']:.6f}")
    print("\nCutoff | References kept | Wrong subjects above | Top-1 | Coverage | Eligible candidates")
    for row in report["sweep"]:
        metrics = row["guarded_top1_metrics"]
        print(f"{row['cutoff']:.2f} | {row['reference_pairs_above_cutoff']}/{row['reference_pair_count']} | {row['negative_pairs_above_cutoff']}/{row['negative_pair_count']} | {metrics['correct_exact_matches']}/{metrics['post_count']} | {metrics['returned_count']}/{metrics['post_count']} | {row['guard_pass_candidates_above_cutoff']}/{row['baseline_guard_pass_candidate_count']}")
    print("Cosine score is not a probability. Subject/context/confidence guards remain necessary.")
    print("No matching policy changed. No Gemini requests sent.")
    print("Report saved:", output)


if __name__ == "__main__":
    main()
