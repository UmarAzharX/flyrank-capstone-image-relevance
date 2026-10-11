from sqlalchemy import select

from app.database import SessionLocal
from app.models import Image, Post, Review, Suggestion
from app.schemas import ReviewCreate, ReviewResponse


def create_review(
    *,
    tenant_id: int,
    suggestion_id: int,
    payload: ReviewCreate,
) -> ReviewResponse:
    for value in (tenant_id, suggestion_id):
        if type(value) is not int or value < 1:
            raise ValueError("Tenant and suggestion IDs must be positive integers.")

    validated = ReviewCreate.model_validate(payload.model_dump())

    with SessionLocal.begin() as db:
        suggestion = db.scalar(
            select(Suggestion)
            .join(Post, Post.id == Suggestion.post_id)
            .join(Image, Image.id == Suggestion.image_id)
            .where(
                Suggestion.id == suggestion_id,
                Suggestion.tenant_id == tenant_id,
                Post.tenant_id == tenant_id,
                Image.tenant_id == tenant_id,
            )
            .with_for_update(of=Suggestion)
        )
        if suggestion is None:
            raise LookupError("Suggestion not found for this tenant.")

        review = Review(
            suggestion_id=suggestion.id,
            decision=validated.decision,
            review_note=validated.review_note,
        )
        db.add(review)
        db.flush()
        response = ReviewResponse.model_validate(review)

    return response
