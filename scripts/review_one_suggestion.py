import argparse

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Image, Post, Review, Suggestion, Tenant
from app.review_processing import create_review
from app.schemas import ReviewCreate


def main() -> None:
    parser = argparse.ArgumentParser(description="Save one human review.")
    parser.add_argument("suggestion_id", type=int)
    parser.add_argument("--decision", required=True, choices=["accept", "reject"])
    parser.add_argument("--note", default=None)
    args = parser.parse_args()

    try:
        payload = ReviewCreate(decision=args.decision, review_note=args.note)
        with SessionLocal() as db:
            tenant_id = db.scalar(
                select(Tenant.id).where(Tenant.name == "FlyRank Demo")
            )
            if tenant_id is None:
                raise LookupError("Demo tenant not found.")

        response = create_review(
            tenant_id=tenant_id,
            suggestion_id=args.suggestion_id,
            payload=payload,
        )

        with SessionLocal() as db:
            row = db.execute(
                select(Review, Image.external_id, Suggestion.guard_decision)
                .join(Suggestion, Suggestion.id == Review.suggestion_id)
                .join(Post, Post.id == Suggestion.post_id)
                .join(Image, Image.id == Suggestion.image_id)
                .where(
                    Review.id == response.id,
                    Suggestion.id == args.suggestion_id,
                    Suggestion.tenant_id == tenant_id,
                    Post.tenant_id == tenant_id,
                    Image.tenant_id == tenant_id,
                )
            ).one()
            review, image_id, guard_decision = row
            if (
                review.decision != payload.decision
                or review.review_note != payload.review_note
            ):
                raise ValueError("Saved review differs from the submitted review.")
            review_id = review.id
            decision = review.decision
            note = review.review_note

    except Exception as exc:
        raise SystemExit(
            f"Review processing failed: {type(exc).__name__}. "
            "Error details withheld to protect secrets."
        ) from None

    print("Review saved and read back from PostgreSQL.")
    print("Review ID:", review_id)
    print("Suggestion ID:", args.suggestion_id)
    print("Image:", image_id)
    print("Human decision:", decision)
    print("Review note:", note)
    print("Automated guard decision:", guard_decision)


if __name__ == "__main__":
    main()
