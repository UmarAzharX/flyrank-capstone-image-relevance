import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import AICallCost, Image, Post, Suggestion, Tenant
from app.ranking import RankedImage
from app.routes import posts
from app import suggestion_processing


class NoMatchApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        manifest_path = Path(self.temp.name) / "images.json"
        manifest_path.write_text(json.dumps([{"id": f"image_{i}"} for i in (1, 2, 3)]), encoding="utf-8")
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.addCleanup(self.engine.dispose)
        with self.sessions.begin() as db:
            db.add_all([Tenant(id=1, name="FlyRank Demo"), Tenant(id=2, name="Other tenant")])
            db.flush()
            for tenant_id in (1, 2):
                db.add(Post(id=tenant_id, tenant_id=tenant_id, external_id="post", title="Wolves in winter", content="Wolves in snow."))
            for i in (1, 2, 3):
                db.add(Image(id=i, tenant_id=1, external_id=f"image_{i}", filename="test.jpg", source="test", source_page_url="https://example.com/image"))

        self.rank_patch = patch.object(suggestion_processing, "rank_images_for_post")
        self.ranking = self.rank_patch.start()
        self.addCleanup(self.rank_patch.stop)
        self.patches = [
            patch.object(suggestion_processing, "SessionLocal", self.sessions),
            patch.object(suggestion_processing.settings, "similarity_threshold", 0.7),
            patch.object(suggestion_processing.settings, "vision_confidence_threshold", 0.8),
            patch.object(posts, "CORPUS_MANIFEST_PATH", manifest_path),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.set_candidates()

        app = FastAPI()
        app.include_router(posts.router)

        def test_db():
            with self.sessions() as db:
                yield db

        app.dependency_overrides[get_db] = test_db
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def set_candidates(self, passing=False):
        candidates = [
            RankedImage(1, "image_1", "wolf", "A wolf in snow." if passing else "A wolf in green grass.", [], 0.99, 0.8),
            RankedImage(2, "image_2", "wolf", "A wolf in snow.", ["snow"], 0.99, 0.69),
            RankedImage(3, "image_3", "Siberian Husky", "A dog in snow.", ["snow"], 0.99, 0.9),
        ]
        self.ranking.return_value = sorted(candidates, key=lambda image: (-image.similarity_score, image.external_id))

    def submit(self, post_id=1, top_k=5):
        return self.client.post(f"/posts/{post_id}/suggestions", params={"top_k": top_k})

    def count(self, model):
        with self.sessions() as db:
            return db.scalar(select(func.count(model.id)))

    def test_abstention_is_200_with_real_guard_reasons_and_no_writes(self):
        response = self.submit()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["match_status"], "no_confident_match")
        self.assertEqual(body["suggestions"], [])
        self.assertEqual((body["created_count"], body["reused_count"]), (0, 0))
        self.assertEqual(body["candidates_checked"], 3)
        reasons = " ".join(body["no_match_reasons"])
        self.assertIn("Subject mismatch", reasons)
        self.assertIn("does not confirm snow", reasons)
        self.assertIn("below the configured cutoff", reasons)
        self.assertEqual(self.count(Suggestion), 0)
        self.assertEqual(self.count(AICallCost), 0)

    def test_matching_response_keeps_existing_fields_and_no_abstention_reasons(self):
        self.set_candidates(passing=True)
        response = self.submit()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["match_status"], "matched")
        self.assertEqual(body["no_match_reasons"], [])
        self.assertEqual(body["created_count"], 1)
        self.assertEqual(body["candidates_checked"], 3)
        self.assertEqual([row["image_external_id"] for row in body["suggestions"]], ["image_1"])
        self.assertIn("cutoff 0.700", body["suggestions"][0]["explanation"])

    def test_repeat_generation_reuses_same_suggestion(self):
        self.set_candidates(passing=True)
        first = self.submit().json()
        second = self.submit().json()
        self.assertEqual(second["created_count"], 0)
        self.assertEqual(second["reused_count"], 1)
        self.assertEqual(first["suggestions"][0]["id"], second["suggestions"][0]["id"])
        self.assertEqual(self.count(Suggestion), 1)
        self.assertEqual(self.count(AICallCost), 0)

    def test_low_confidence_abstention_preserves_specific_reason(self):
        self.ranking.return_value = [RankedImage(i, f"image_{i}", "wolf", "A wolf in snow.", ["snow"], 0.6, 0.9) for i in (1, 2, 3)]
        body = self.submit().json()
        self.assertEqual(body["match_status"], "no_confident_match")
        self.assertTrue(any("Vision confidence" in reason and "below" in reason for reason in body["no_match_reasons"]))

    def test_all_low_scores_return_no_match_with_cutoff_reason(self):
        self.ranking.return_value = [RankedImage(i, f"image_{i}", "wolf", "A wolf in snow.", ["snow"], 0.99, 0.3) for i in (1, 2, 3)]
        response = self.submit()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["match_status"], "no_confident_match")
        self.assertTrue(any("below the configured cutoff" in reason for reason in response.json()["no_match_reasons"]))
        self.assertEqual(self.count(Suggestion), 0)

    def test_missing_post_returns_404_without_ranking(self):
        response = self.submit(post_id=999)
        self.assertEqual(response.status_code, 404)
        self.ranking.assert_not_called()

    def test_other_tenant_post_is_hidden_without_diagnostics(self):
        response = self.submit(post_id=2)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Post not found"})
        self.ranking.assert_not_called()

    def test_invalid_post_ids_are_422(self):
        for post_id in (0, -1, "invalid"):
            with self.subTest(post_id=post_id):
                self.assertEqual(self.submit(post_id=post_id).status_code, 422)
        self.ranking.assert_not_called()

    def test_invalid_limits_are_422(self):
        for limit in (0, -1, 51, "invalid"):
            with self.subTest(limit=limit):
                self.assertEqual(self.submit(top_k=limit).status_code, 422)
        self.ranking.assert_not_called()

    def test_not_ready_is_409_not_a_normal_abstention(self):
        self.ranking.side_effect = LookupError("private embedding details")
        response = self.submit()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"detail": "Post is not ready for matching. Check saved descriptions and embeddings."})
        self.assertEqual(self.count(Suggestion), 0)

    def test_internal_errors_are_safe_500_responses(self):
        self.ranking.side_effect = RuntimeError("private connection details")
        response = self.submit()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"detail": "Unable to generate suggestions."})
        self.assertEqual(self.count(Suggestion), 0)

    def test_diagnostics_are_bounded_to_the_nearest_three(self):
        from app.mismatch_guard import MismatchGuardResult
        candidates = [
            (RankedImage(i, f"image_{i}", "wolf", "Wolf.", [], 0.99, 0.9), MismatchGuardResult("review", f"Reason {i}"))
            for i in (1, 2, 3, 4)
        ]
        reasons = suggestion_processing.explain_no_match(candidates)
        self.assertEqual(len(reasons), 4)
        self.assertIn("4 candidates", reasons[0])
        self.assertNotIn("Reason 4", " ".join(reasons))


if __name__ == "__main__":
    unittest.main()
