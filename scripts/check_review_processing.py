import unittest
from unittest.mock import patch

from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Image, Post, Review, Suggestion, Tenant
from app.review_processing import create_review
from app.schemas import ReviewCreate


class ReviewProcessingTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.session_patch = patch("app.review_processing.SessionLocal", self.sessions)
        self.session_patch.start()
        with self.sessions.begin() as db:
            db.add_all([Tenant(id=1, name="First"), Tenant(id=2, name="Second")])
            db.flush()
            for tenant_id in (1, 2):
                db.add(Post(id=tenant_id, tenant_id=tenant_id, external_id="post", title="Wolves in snow", content="Winter wolves."))
                db.add(Image(id=tenant_id, tenant_id=tenant_id, external_id="image", filename="wolf.jpg", source="test", source_page_url="https://example.com/image"))
            db.flush()
            db.add(Suggestion(id=1, tenant_id=1, post_id=1, image_id=1, similarity_score=0.75, guard_decision="pass", explanation="Wolf in snow."))

    def tearDown(self):
        self.session_patch.stop()
        self.engine.dispose()

    def review_count(self):
        with self.sessions() as db:
            return db.scalar(select(func.count(Review.id)))

    def submit(self, decision="accept", tenant_id=1, suggestion_id=1):
        return create_review(tenant_id=tenant_id, suggestion_id=suggestion_id, payload=ReviewCreate(decision=decision, review_note="Editorial decision."))

    def test_accept_is_persisted_and_linked_to_suggestion(self):
        result = self.submit()
        with self.sessions() as db:
            saved = db.get(Review, result.id)
            self.assertEqual(saved.suggestion_id, 1)
            self.assertEqual(saved.decision, "accept")
            self.assertEqual(saved.review_note, "Editorial decision.")

    def test_human_rejection_preserves_automated_guard(self):
        result = self.submit("reject")
        with self.sessions() as db:
            self.assertEqual(db.get(Review, result.id).decision, "reject")
            self.assertEqual(db.get(Suggestion, 1).guard_decision, "pass")

    def test_missing_suggestion_creates_no_review(self):
        with self.assertRaises(LookupError):
            self.submit(suggestion_id=999)
        self.assertEqual(self.review_count(), 0)

    def test_other_tenant_cannot_review_suggestion(self):
        with self.assertRaises(LookupError):
            self.submit(tenant_id=2)
        self.assertEqual(self.review_count(), 0)

    def test_inconsistent_post_ownership_is_blocked(self):
        with self.sessions.begin() as db:
            db.get(Suggestion, 1).post_id = 2
        with self.assertRaises(LookupError):
            self.submit()
        self.assertEqual(self.review_count(), 0)

    def test_inconsistent_image_ownership_is_blocked(self):
        with self.sessions.begin() as db:
            db.get(Suggestion, 1).image_id = 2
        with self.assertRaises(LookupError):
            self.submit()
        self.assertEqual(self.review_count(), 0)

    def test_bypassed_schema_validation_is_rechecked(self):
        invalid = ReviewCreate.model_construct(decision="approve", review_note=None)
        with self.assertRaises(ValidationError):
            create_review(tenant_id=1, suggestion_id=1, payload=invalid)
        self.assertEqual(self.review_count(), 0)

    def test_later_review_preserves_earlier_history(self):
        accepted = self.submit("accept")
        rejected = self.submit("reject")
        self.assertNotEqual(accepted.id, rejected.id)
        with self.sessions() as db:
            history = db.scalars(select(Review).order_by(Review.id)).all()
            self.assertEqual([review.decision for review in history], ["accept", "reject"])

    def test_failure_after_insert_rolls_back_review(self):
        with patch("app.review_processing.ReviewResponse.model_validate", side_effect=RuntimeError("Test failure")):
            with self.assertRaises(RuntimeError):
                self.submit()
        self.assertEqual(self.review_count(), 0)

    def test_invalid_ids_create_no_review(self):
        for value in (0, -1, True, "1"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.submit(suggestion_id=value)
        self.assertEqual(self.review_count(), 0)


if __name__ == "__main__":
    unittest.main()
