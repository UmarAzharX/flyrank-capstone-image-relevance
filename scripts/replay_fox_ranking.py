"""Compare a fox post with the strongest wolf and dog using saved vectors."""

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
from app.subject_guard import evaluate_subject_match

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POST_EXTERNAL_ID = "post_001"


def describes(item, animal):
    return evaluate_subject_match(
        post_title=animal, post_content="", image_subject=item.subject
    ).decision == "pass"


def analyze_ranking(ranked, title, content):
    if not ranked:
        raise ValueError("No ranked candidates.")
    selected = {"first_result": (1, ranked[0])}
    for animal in ("wolf", "dog"):
        selected["best_" + animal] = next(
            ((rank, item) for rank, item in enumerate(ranked, 1)
             if describes(item, animal)), None
        )
    details = {}
    for label, pair in selected.items():
        if pair is None:
            details[label] = None
            continue
        rank, item = pair
        subject = evaluate_subject_match(
            post_title=title, post_content=content, image_subject=item.subject
        )
        guard = evaluate_mismatch(
            post_title=title, post_content=content,
            image_subject=item.subject, image_caption=item.caption,
            image_attributes=item.attributes, image_confidence=item.confidence,
            confidence_threshold=settings.vision_confidence_threshold,
            similarity_score=item.similarity_score,
            similarity_threshold=settings.similarity_threshold,
        )
        details[label] = {
            "raw_rank": rank, "image_id": item.image_id,
            "external_id": item.external_id, "subject": item.subject,
            "cosine_score": item.similarity_score,
            "vision_confidence": item.confidence,
            "subject_decision": subject.decision,
            "guard_decision": guard.decision, "explanation": guard.explanation,
        }
    first = details["first_result"]
    checks = {
        "raw_top_1_is_fox": describes(ranked[0], "fox"),
        "top_1_passes_all_guards": first["guard_decision"] == "pass",
    }
    for animal in ("wolf", "dog"):
        other = details["best_" + animal]
        checks["fox_scores_above_best_" + animal] = (
            other is not None and first["cosine_score"] > other["cosine_score"]
        )
        checks[animal + "_rejected_by_subject_and_full_guard"] = (
            other is not None and other["subject_decision"] == "reject"
            and other["guard_decision"] == "reject"
        )
        if other is not None:
            other["score_gap_below_first"] = first["cosine_score"] - other["cosine_score"]
    return details, checks


def main():
    try:
        manifest = json.loads((PROJECT_ROOT / "data/images.json").read_text(encoding="utf-8-sig"))
        corpus_ids = {row["id"] for row in manifest}
        if not corpus_ids or len(corpus_ids) != len(manifest):
            raise ValueError("Invalid corpus manifest.")
        with SessionLocal() as db:
            tenant_id = db.scalar(select(Tenant.id).where(Tenant.name == "FlyRank Demo"))
            if tenant_id is None:
                raise LookupError("Demo tenant not found.")
            post = db.scalar(select(Post).where(
                Post.tenant_id == tenant_id, Post.external_id == POST_EXTERNAL_ID
            ))
            if post is None:
                raise LookupError("Post not found.")
            post_id, title, content = post.id, post.title, post.content
        ranked = rank_images_for_post(
            tenant_id=tenant_id, external_id=POST_EXTERNAL_ID,
            corpus_ids=corpus_ids, top_k=len(corpus_ids),
        )
        details, checks = analyze_ranking(ranked, title, content)
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "post_external_id": POST_EXTERNAL_ID, "post_id": post_id,
            "post_title": title, "post_content": content, "tenant_id": tenant_id,
            "embedding_profile": EMBEDDING_PROFILE,
            "candidates_checked": len(ranked),
            "similarity_threshold": settings.similarity_threshold,
            "vision_confidence_threshold": settings.vision_confidence_threshold,
            "score_source": "Measured cosine similarity from stored post and image vectors.",
            "comparison": details, "checks": checks, "passed": all(checks.values()),
            "database_writes": 0, "gemini_requests_sent": 0,
            "limitations": [
                "This is one development query, not an independent evaluation.",
                "Score gaps are measured differences, not probabilities or calibrated margins.",
            ],
        }
        reports = PROJECT_ROOT / "reports"
        reports.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        output = reports / f"fox_ranking_{stamp}.json"
        with output.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, allow_nan=False)
            handle.write("\n")
    except Exception as exc:
        raise SystemExit(f"Ranking replay failed: {type(exc).__name__}. Error details withheld to protect secrets.") from None
    print("Post:", POST_EXTERNAL_ID)
    print("Candidates checked:", len(ranked))
    for label, row in details.items():
        if row is None:
            print(label + ": no candidate found.")
        else:
            print(f"{label}: rank={row['raw_rank']} | image={row['external_id']} | "
                  f"score={row['cosine_score']:.6f} | guard={row['guard_decision']}")
            print("Explanation:", row["explanation"])
            if "score_gap_below_first" in row:
                print(f"Score gap below first: {row['score_gap_below_first']:.6f}")
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
    print("No database writes or Gemini requests. Evaluation data was not changed.")
    print("Report saved:", output)
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

