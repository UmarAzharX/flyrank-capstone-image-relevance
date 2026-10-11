from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Image, Post, Review, Suggestion
from app.review_processing import create_review
from app.routes.posts import get_demo_tenant
from app.schemas import ReviewCreate, ReviewResponse


router = APIRouter(prefix="/suggestions", tags=["reviews"])


@router.post(
    "/{suggestion_id}/reviews",
    response_model=ReviewResponse,
    status_code=201,
)
def submit_suggestion_review(
    suggestion_id: Annotated[int, Path(ge=1)],
    payload: ReviewCreate,
    db: Session = Depends(get_db),
) -> ReviewResponse:
    try:
        tenant = get_demo_tenant(db)
        return create_review(
            tenant_id=tenant.id,
            suggestion_id=suggestion_id,
            payload=payload,
        )
    except HTTPException:
        raise
    except LookupError:
        raise HTTPException(status_code=404, detail="Suggestion not found") from None
    except Exception:
        raise HTTPException(status_code=500, detail="Unable to save review") from None


@router.get(
    "/{suggestion_id}/reviews",
    response_model=list[ReviewResponse],
)
def list_suggestion_reviews(
    suggestion_id: Annotated[int, Path(ge=1)],
    db: Session = Depends(get_db),
) -> list[ReviewResponse]:
    try:
        tenant = get_demo_tenant(db)
        # A left join distinguishes a missing suggestion from an empty history.
        rows = db.scalars(
            select(Review)
            .select_from(Suggestion)
            .join(Post, Post.id == Suggestion.post_id)
            .join(Image, Image.id == Suggestion.image_id)
            .outerjoin(Review, Review.suggestion_id == Suggestion.id)
            .where(
                Suggestion.id == suggestion_id,
                Suggestion.tenant_id == tenant.id,
                Post.tenant_id == tenant.id,
                Image.tenant_id == tenant.id,
            )
            .order_by(Review.id)
        ).all()
        if not rows:
            raise HTTPException(status_code=404, detail="Suggestion not found")
        return [ReviewResponse.model_validate(row) for row in rows if row is not None]
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Unable to read reviews") from None
