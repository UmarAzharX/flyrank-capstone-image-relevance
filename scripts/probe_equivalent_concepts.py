"""Run a separate scientific-name probe through the production embedding path."""
import json
from datetime import datetime, timezone
from pathlib import Path

from google.genai import errors
from sqlalchemy import select

from app.budget import AIUsageLimitError
from app.config import settings
from app.database import SessionLocal
from app.embedding_text import build_post_embedding_text
from app.embedding_vectors import EMBEDDING_PROFILE
from app.mismatch_guard import evaluate_mismatch
from app.models import Post, Tenant
from app.post_embeddings import embed_post
from app.ranking import rank_images_for_post
from app.schemas import PostCreate
from app.subject_guard import evaluate_subject_match


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROBE_ID = "probe_vulpes_vulpes_v1"
PROBE_TITLE = "Vulpes vulpes"
PROBE_CONTENT = "A close-up portrait of Vulpes vulpes."


def prepare_probe():
    # Keep this fixture separate from the hand-labelled evaluation posts.
    payload = PostCreate(
        external_id=PROBE_ID, title=PROBE_TITLE, content=PROBE_CONTENT
    )
    if evaluate_subject_match(
        post_title=payload.title, post_content=payload.content,
        image_subject="Red fox",
    ).decision != "pass":
        raise ValueError("The scientific-name subject alias must be installed first.")
    with SessionLocal.begin() as db:
        tenant = db.scalar(
            select(Tenant).where(Tenant.name == "FlyRank Demo").with_for_update()
        )
        if tenant is None:
            raise LookupError("Demo tenant not found.")
        post = db.scalar(select(Post).where(
            Post.tenant_id == tenant.id, Post.external_id == PROBE_ID
        ).with_for_update())
        if post is None:
            post = Post(tenant_id=tenant.id, **payload.model_dump())
            db.add(post)
            db.flush()
        elif post.title != payload.title or post.content != payload.content:
            raise ValueError("Saved probe text differs; its embedding could be stale.")
        return tenant.id


def inspect_ranking(ranked):
    if not ranked:
        raise ValueError("Empty corpus ranking.")
    candidates = []
    for position, item in enumerate(ranked, start=1):
        subject = evaluate_subject_match(
            post_title=PROBE_TITLE, post_content=PROBE_CONTENT,
            image_subject=item.subject,
        )
        guard = evaluate_mismatch(
            post_title=PROBE_TITLE, post_content=PROBE_CONTENT,
            image_subject=item.subject, image_caption=item.caption,
            image_attributes=item.attributes, image_confidence=item.confidence,
            confidence_threshold=settings.vision_confidence_threshold,
            similarity_score=item.similarity_score,
            similarity_threshold=settings.similarity_threshold,
        )
        candidates.append({
            "rank": position, "image_id": item.external_id,
            "subject": item.subject, "caption": item.caption,
            "similarity_score": item.similarity_score,
            "vision_confidence": item.confidence,
            "subject_decision": subject.decision,
            "guard_decision": guard.decision, "explanation": guard.explanation,
        })

    # Corpus IDs are audited family labels used to assess the probe only.
    # No family preference or expected image is passed into ranking.
    wolves = [item for item in candidates if item["image_id"].startswith("wolf_")]
    eligible = [item for item in candidates if item["guard_decision"] == "pass"]
    checks = {
        "raw_top_1_is_fox": candidates[0]["image_id"].startswith("fox_"),
        "eligible_top_1_is_fox": bool(eligible) and eligible[0]["image_id"].startswith("fox_"),
        "fox_scores_above_best_wolf": bool(wolves) and candidates[0]["image_id"].startswith("fox_")
        and candidates[0]["similarity_score"] > wolves[0]["similarity_score"],
        "all_wolves_rejected_by_subject": bool(wolves)
        and all(item["subject_decision"] == "reject" for item in wolves),
    }
    return candidates, wolves[0] if wolves else None, checks


def run_probe(corpus_ids):
    tenant_id = prepare_probe()
    # Uses the existing reservation, cost logging, normalization and cache.
    embedding_id, created = embed_post(tenant_id=tenant_id, external_id=PROBE_ID)
    ranked = rank_images_for_post(
        tenant_id=tenant_id, external_id=PROBE_ID,
        corpus_ids=corpus_ids, top_k=len(corpus_ids),
    )
    candidates, best_wolf, checks = inspect_ranking(ranked)
    return {
        "probe_version": "equivalent-concepts-v1",
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "scope": "One development probe; separate from the 10-post evaluation.",
        "source": "https://www.nps.gov/articles/red-fox.htm",
        "post": {"external_id": PROBE_ID, "title": PROBE_TITLE, "content": PROBE_CONTENT},
        "embedding_input": build_post_embedding_text(title=PROBE_TITLE, content=PROBE_CONTENT),
        "embedding_id": embedding_id, "embedding_created": created,
        "embedding_profile": EMBEDDING_PROFILE,
        "similarity_threshold": settings.similarity_threshold,
        "vision_confidence_threshold": settings.vision_confidence_threshold,
        "candidates_checked": len(candidates),
        "checks": checks, "passed": all(checks.values()),
        "highest_scoring_wolf": best_wolf, "candidates": candidates,
    }


def show_candidate(item):
    print(f"{item['rank']}. {item['image_id']} | score={item['similarity_score']:.6f} "
          f"| subject={item['subject']} | guard={item['guard_decision']}")
    print("   Explanation:", item["explanation"])


def main():
    try:
        manifest = json.loads((PROJECT_ROOT / "data" / "images.json").read_text(encoding="utf-8"))
        corpus_ids = {item["id"] for item in manifest}
        if not corpus_ids or len(corpus_ids) != len(manifest):
            raise ValueError("Invalid corpus manifest.")
        print("Probe post:", PROBE_ID)
        print("Embedding input:")
        print(build_post_embedding_text(title=PROBE_TITLE, content=PROBE_CONTENT))
        report = run_probe(corpus_ids)
        reports_dir = PROJECT_ROOT / "reports"
        reports_dir.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        output = reports_dir / f"equivalent_concepts_v1_{stamp}.json"
        with output.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, allow_nan=False)
            handle.write("\n")
    except AIUsageLimitError as exc:
        raise SystemExit(f"Probe blocked: {exc}") from None
    except errors.APIError as exc:
        raise SystemExit(f"Probe request failed: HTTP {exc.code}.") from None
    except Exception as exc:
        raise SystemExit(f"Probe failed: {type(exc).__name__}. Error details withheld to protect secrets.") from None

    print("New probe embedding saved." if report["embedding_created"]
          else "Probe embedding reused. No Gemini request sent.")
    print("Corpus candidates:", report["candidates_checked"])
    print("Raw cosine ranking (before guard filtering):")
    for item in report["candidates"][:5]:
        show_candidate(item)
    print("Highest-scoring wolf:")
    if report["highest_scoring_wolf"]:
        show_candidate(report["highest_scoring_wolf"])
    else:
        print("No wolf candidate found.")
    for name, passed in report["checks"].items():
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
    print("Report saved:", output)
    print("This probe does not change the 10-post evaluation score.")
    if not report["passed"]:
        raise SystemExit("Probe did not pass all checks; inspect the measured results.")


if __name__ == "__main__":
    main()
