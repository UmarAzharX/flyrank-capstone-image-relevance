from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.mismatch_guard import evaluate_mismatch
from app.models import Post, Suggestion
from app.ranking import rank_images_for_post
from app.selection import select_eligible_candidates


def save_post_suggestions(
    *,
    tenant_id: int,
    external_id: str,
    corpus_ids: set[str],
    limit: int = 5,
) -> tuple[list[int], int]:
    if not corpus_ids or type(limit) is not int or limit < 1:
        raise ValueError("Invalid corpus or suggestion limit.")

    saved_ids = []
    created_count = 0

    with SessionLocal.begin() as db:
        post = db.scalar(
            select(Post)
            .where(
                Post.tenant_id == tenant_id,
                Post.external_id == external_id,
            )
            .with_for_update()
        )
        if post is None:
            raise LookupError("Post not found.")

        ranked = rank_images_for_post(
            tenant_id=tenant_id,
            external_id=external_id,
            corpus_ids=corpus_ids,
            top_k=len(corpus_ids),
        )

        guarded = [
            (
                image,
                evaluate_mismatch(
                    post_title=post.title,
                    post_content=post.content,
                    image_subject=image.subject,
                    image_caption=image.caption,
                    image_attributes=image.attributes,
                    image_confidence=image.confidence,
                    confidence_threshold=settings.vision_confidence_threshold,
                ),
            )
            for image in ranked
        ]
        selected = select_eligible_candidates(
            guarded,
            limit=limit,
        )

        for image, guard in selected:
            suggestion = db.scalars(
                select(Suggestion).where(
                    Suggestion.tenant_id == tenant_id,
                    Suggestion.post_id == post.id,
                    Suggestion.image_id == image.image_id,
                )
            ).one_or_none()

            if suggestion is None:
                suggestion = Suggestion(
                    tenant_id=tenant_id,
                    post_id=post.id,
                    image_id=image.image_id,
                    similarity_score=image.similarity_score,
                    guard_decision=guard.decision,
                    explanation=guard.explanation,
                )
                db.add(suggestion)
                created_count += 1
            else:
                suggestion.similarity_score = image.similarity_score
                suggestion.guard_decision = guard.decision
                suggestion.explanation = guard.explanation

            db.flush()
            saved_ids.append(suggestion.id)

    return saved_ids, created_count
