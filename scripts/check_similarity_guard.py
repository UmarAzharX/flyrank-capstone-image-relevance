import unittest
from unittest.mock import patch

from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.database import Base
from app.mismatch_guard import evaluate_mismatch
from app.models import Image, Post, Suggestion, Tenant
from app.ranking import RankedImage
from app.similarity_guard import evaluate_similarity
from app import suggestion_processing


def combined(score=0.9, threshold=0.7, subject="wolf", confidence=0.99):
    return evaluate_mismatch(
        post_title="Wolves in winter", post_content="Wolves in snow.",
        image_subject=subject, image_caption=f"A {subject} in snow.",
        image_attributes=["snow"], image_confidence=confidence,
        confidence_threshold=0.8, similarity_score=score,
        similarity_threshold=threshold,
    )


class SimilarityGuardTests(unittest.TestCase):
    def test_below_cutoff_rejects_with_reason(self):
        result = evaluate_similarity(score=0.6999999, threshold=0.7)
        self.assertEqual(result.decision, "reject")
        self.assertIn("below", result.explanation)
        self.assertIn("0.6999999", result.explanation)

    def test_equal_cutoff_passes(self):
        self.assertEqual(evaluate_similarity(score=0.7, threshold=0.7).decision, "pass")

    def test_above_cutoff_passes(self):
        self.assertEqual(evaluate_similarity(score=0.9, threshold=0.7).decision, "pass")

    def test_negative_cosine_is_valid_but_below_positive_cutoff(self):
        self.assertEqual(evaluate_similarity(score=-0.2, threshold=0.7).decision, "reject")

    def test_missing_nonfinite_and_invalid_scores_need_review(self):
        for score in (None, True, float("nan"), float("inf"), float("-inf"), -1.01, 1.01, "0.9"):
            with self.subTest(score=score):
                self.assertEqual(evaluate_similarity(score=score, threshold=0.7).decision, "review")

    def test_invalid_cutoff_fails_configuration(self):
        for threshold in (None, True, float("nan"), float("inf"), -1.01, 1.01, "0.7"):
            with self.subTest(threshold=threshold), self.assertRaises(ValueError):
                evaluate_similarity(score=0.8, threshold=threshold)

    def test_config_enforces_finite_zero_to_one_cutoff(self):
        self.assertEqual(Settings(_env_file=None, similarity_threshold=0.72).similarity_threshold, 0.72)
        for threshold in (-0.01, 1.01, float("nan"), float("inf")):
            with self.subTest(threshold=threshold), self.assertRaises(ValidationError):
                Settings(_env_file=None, similarity_threshold=threshold)


class CombinedSimilarityTests(unittest.TestCase):
    def test_low_score_blocks_otherwise_matching_image(self):
        self.assertEqual(combined(0.69).decision, "reject")

    def test_boundary_matching_image_passes(self):
        self.assertEqual(combined(0.7).decision, "pass")

    def test_high_score_does_not_override_wrong_subject(self):
        result = combined(0.99, subject="Siberian Husky")
        self.assertEqual(result.decision, "reject")
        self.assertIn("Subject mismatch", result.explanation)

    def test_missing_score_prevents_automatic_pass(self):
        self.assertEqual(combined(None).decision, "review")

    def test_high_score_does_not_override_low_vision_confidence(self):
        self.assertEqual(combined(0.99, confidence=0.6).decision, "review")

    def test_configured_cutoff_reaches_combined_guard(self):
        self.assertEqual(combined(0.8, threshold=0.85).decision, "reject")


class SuggestionSimilarityTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.session_patch = patch.object(suggestion_processing, "SessionLocal", self.sessions)
        self.session_patch.start()
        self.addCleanup(self.session_patch.stop)
        self.addCleanup(self.engine.dispose)
        with self.sessions.begin() as db:
            db.add(Tenant(id=1, name="Test"))
            db.flush()
            db.add(Post(id=1, tenant_id=1, external_id="post", title="Wolves in winter", content="Wolves in snow."))
            for i in range(1, 4):
                db.add(Image(id=i, tenant_id=1, external_id=f"image_{i}", filename="test.jpg", source="test", source_page_url="https://example.com/image"))
        self.candidates = [
            RankedImage(1, "image_1", "wolf", "A wolf in snow.", ["snow"], 0.99, 0.69),
            RankedImage(2, "image_2", "wolf", "A wolf in snow.", ["snow"], 0.99, 0.80),
            RankedImage(3, "image_3", "dog", "A dog in snow.", ["snow"], 0.99, 0.99),
        ]

    def save(self, threshold):
        with patch.object(suggestion_processing, "rank_images_for_post", return_value=self.candidates), patch.object(suggestion_processing.settings, "similarity_threshold", threshold):
            return suggestion_processing.save_post_suggestions(tenant_id=1, external_id="post", corpus_ids={"image_1", "image_2", "image_3"}, limit=5)

    def test_only_passing_subject_and_score_are_persisted(self):
        ids, created = self.save(0.7)
        self.assertEqual(created, 1)
        with self.sessions() as db:
            suggestions = db.scalars(select(Suggestion)).all()
            self.assertEqual([item.id for item in suggestions], ids)
            self.assertEqual([item.image_id for item in suggestions], [2])
            self.assertIn("configured cutoff 0.700", suggestions[0].explanation)

    def test_custom_cutoff_can_leave_no_suggestions(self):
        self.assertEqual(self.save(0.85), ([], 0))
        with self.sessions() as db:
            self.assertEqual(db.scalars(select(Suggestion)).all(), [])

    def test_repeat_save_reuses_existing_suggestion(self):
        first, created = self.save(0.7)
        second, created_again = self.save(0.7)
        self.assertEqual((created, created_again), (1, 0))
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
