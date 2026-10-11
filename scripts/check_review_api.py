import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import Image, Post, Review, Suggestion, Tenant
from app.routes.reviews import router


class ReviewApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        with self.sessions.begin() as db:
            db.add_all([Tenant(id=1, name="FlyRank Demo"), Tenant(id=2, name="Other tenant")])
            db.flush()
            for tenant_id in (1, 2):
                db.add(Post(id=tenant_id, tenant_id=tenant_id, external_id="post", title="Wolves in snow", content="Winter wolves."))
                db.add(Image(id=tenant_id, tenant_id=tenant_id, external_id="image", filename="wolf.jpg", source="test", source_page_url="https://example.com/image"))
            db.flush()
            for tenant_id in (1, 2):
                db.add(Suggestion(id=tenant_id, tenant_id=tenant_id, post_id=tenant_id, image_id=tenant_id, similarity_score=0.75, guard_decision="pass", explanation="Wolf in snow."))

        app = FastAPI()
        app.include_router(router)

        def test_db():
            with self.sessions() as db:
                yield db

        app.dependency_overrides[get_db] = test_db
        self.session_patch = patch("app.review_processing.SessionLocal", self.sessions)
        self.session_patch.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.session_patch.stop()
        self.engine.dispose()

    def count_reviews(self):
        with self.sessions() as db:
            return db.scalar(select(func.count(Review.id)))

    def submit(self, suggestion_id=1, decision="accept", **extra):
        return self.client.post(
            f"/suggestions/{suggestion_id}/reviews",
            json={"decision": decision, **extra},
        )

    def test_post_creates_and_returns_review(self):
        response = self.submit(review_note="Good fit.")
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["suggestion_id"], 1)
        self.assertEqual(body["decision"], "accept")
        self.assertEqual(body["review_note"], "Good fit.")
        self.assertIn("created_at", body)
        self.assertEqual(self.count_reviews(), 1)

    def test_history_preserves_order_and_previous_decisions(self):
        first = self.submit().json()
        second = self.submit(decision="reject").json()
        response = self.client.get("/suggestions/1/reviews")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.json()], [first["id"], second["id"]])
        self.assertEqual([row["decision"] for row in response.json()], ["accept", "reject"])

    def test_valid_suggestion_without_reviews_returns_empty_list(self):
        response = self.client.get("/suggestions/1/reviews")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_missing_suggestion_returns_404_on_both_routes(self):
        for response in (self.submit(suggestion_id=999), self.client.get("/suggestions/999/reviews")):
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), {"detail": "Suggestion not found"})
        self.assertEqual(self.count_reviews(), 0)

    def test_other_tenant_is_hidden_on_both_routes(self):
        for response in (self.submit(suggestion_id=2), self.client.get("/suggestions/2/reviews")):
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), {"detail": "Suggestion not found"})
        self.assertEqual(self.count_reviews(), 0)

    def test_invalid_decision_is_rejected_before_persistence(self):
        self.assertEqual(self.submit(decision="approve").status_code, 422)
        self.assertEqual(self.count_reviews(), 0)

    def test_missing_decision_is_rejected(self):
        response = self.client.post("/suggestions/1/reviews", json={})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.count_reviews(), 0)

    def test_unexpected_fields_are_rejected(self):
        for fields in ({"tenant_id": 2}, {"guard_decision": "pass"}):
            with self.subTest(fields=fields):
                self.assertEqual(self.submit(**fields).status_code, 422)
        self.assertEqual(self.count_reviews(), 0)

    def test_oversized_note_is_rejected(self):
        self.assertEqual(self.submit(review_note="x" * 2001).status_code, 422)
        self.assertEqual(self.count_reviews(), 0)

    def test_invalid_suggestion_id_is_rejected_on_both_routes(self):
        for suggestion_id in (0, -1):
            with self.subTest(suggestion_id=suggestion_id):
                self.assertEqual(self.submit(suggestion_id=suggestion_id).status_code, 422)
                self.assertEqual(self.client.get(f"/suggestions/{suggestion_id}/reviews").status_code, 422)
        self.assertEqual(self.count_reviews(), 0)

    def test_human_rejection_does_not_change_guard_result(self):
        self.assertEqual(self.submit(decision="reject").status_code, 201)
        with self.sessions() as db:
            self.assertEqual(db.get(Suggestion, 1).guard_decision, "pass")

    def test_internal_error_details_are_not_exposed(self):
        with patch("app.routes.reviews.create_review", side_effect=RuntimeError("private connection details")):
            response = self.submit()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"detail": "Unable to save review"})
        self.assertEqual(self.count_reviews(), 0)


if __name__ == "__main__":
    unittest.main()
