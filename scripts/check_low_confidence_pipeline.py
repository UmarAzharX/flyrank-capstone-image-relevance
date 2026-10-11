"""Controlled vision-response fixtures; never calls Gemini or the live database."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app import image_processing, ranking, suggestion_processing
from app.database import Base
from app.embedding_vectors import EMBEDDING_DIMENSIONS, EMBEDDING_PROFILE
from app.models import AICallCost, Embedding, Image, ImageMetadata, Post, Suggestion, Tenant
from app.schemas import VisionMetadata


class LowConfidencePipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        # File contents are not decoded: the vision response is mocked explicitly.
        (root / "controlled.jpg").write_bytes(b"controlled test placeholder")
        self.engine = create_engine("sqlite:///:memory:")
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        with self.sessions.begin() as db:
            db.add(Tenant(id=1, name="Controlled fixture tenant"))
            db.flush()
            db.add(Image(id=1, tenant_id=1, external_id="fixture_fox", filename="controlled.jpg",
                         source="controlled_fixture", source_page_url="https://example.com/fixture"))
            db.add(Post(id=1, tenant_id=1, external_id="fixture_post",
                        title="A close-up of a red fox", content="A close-up portrait of a red fox."))
        for module in (image_processing, ranking, suggestion_processing):
            self.start_patch(patch.object(module, "SessionLocal", self.sessions))
        self.start_patch(patch.object(image_processing, "IMAGE_ROOT", root))
        self.start_patch(patch.object(image_processing.settings, "vision_confidence_threshold", 0.80))
        self.start_patch(patch.object(suggestion_processing.settings, "similarity_threshold", 0.70))
        self.reserve = self.start_patch(patch.object(image_processing, "reserve_free_tier_vision_call", return_value=1))
        self.finish = self.start_patch(patch.object(image_processing, "finish_free_tier_vision_call"))
        self.vision = self.start_patch(patch.object(image_processing, "analyze_image"))

    def start_patch(self, item):
        mock = item.start()
        self.addCleanup(item.stop)
        return mock

    def process(self, confidence):
        metadata = VisionMetadata(
            subject="Red fox", category="Animal", attributes=["close-up"],
            caption="A close-up portrait of a red fox.", confidence=confidence,
        )

        def response(path, on_usage):
            on_usage(image_processing.VISION_MODEL, {"usage_available": False, "controlled_fixture": True})
            return metadata

        self.vision.side_effect = response
        with redirect_stdout(StringIO()):
            return image_processing.process_image(tenant_id=1, external_id="fixture_fox")

    def saved_state(self):
        # New session demonstrates the transaction committed the flag and status.
        with self.sessions() as db:
            image = db.get(Image, 1)
            return image.processing_status, image.image_metadata.low_confidence, image.image_metadata.confidence

    def test_below_threshold_is_saved_with_review_flag(self):
        self.assertEqual(self.process(0.60), 1)
        self.assertEqual(self.saved_state(), ("needs_review", True, 0.60))
        self.finish.assert_called_once()
        self.assertTrue(self.finish.call_args.kwargs["usage"]["controlled_fixture"])

    def test_exact_threshold_is_tagged_without_low_confidence_flag(self):
        self.process(0.80)
        self.assertEqual(self.saved_state(), ("tagged", False, 0.80))

    def test_above_threshold_is_tagged_without_low_confidence_flag(self):
        self.process(0.99)
        self.assertEqual(self.saved_state(), ("tagged", False, 0.99))

    def test_review_metadata_is_reused_without_another_vision_request(self):
        self.process(0.60)
        self.assertIsNone(self.process(0.99))
        self.assertEqual(self.saved_state(), ("needs_review", True, 0.60))
        self.reserve.assert_called_once()
        self.vision.assert_called_once()
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count(ImageMetadata.id))), 1)

    def test_high_similarity_cannot_automatically_select_low_confidence_image(self):
        self.process(0.60)
        # Synthetic identical vectors give cosine=1.0, isolating confidence as
        # the sole blocker while the real ranking and persistence code runs.
        vector = [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)
        with self.sessions.begin() as db:
            for owner in ("image", "post"):
                db.add(Embedding(tenant_id=1, owner_type=owner, owner_id=1,
                                 model_name=EMBEDDING_PROFILE, vector=vector))
        ranked = ranking.rank_images_for_post(tenant_id=1, external_id="fixture_post",
                                             corpus_ids={"fixture_fox"}, top_k=1)
        self.assertEqual(ranked[0].similarity_score, 1.0)
        result = suggestion_processing.generate_post_suggestions(
            tenant_id=1, external_id="fixture_post", corpus_ids={"fixture_fox"}, limit=5
        )
        self.assertEqual(result.match_status, "no_confident_match")
        self.assertEqual((result.saved_ids, result.created_count), ([], 0))
        self.assertEqual(result.candidates_checked, 1)
        reasons = " ".join(result.no_match_reasons)
        self.assertIn("Vision confidence 0.600 is below", reasons)
        self.assertIn("configured threshold 0.800", reasons)
        self.assertIn("Subject check passed", reasons)
        self.assertIn("context: close-up view", reasons)
        self.assertIn("Cosine similarity 1.000000 meets", reasons)
        self.assertEqual(self.saved_state(), ("needs_review", True, 0.60))
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(func.count(Suggestion.id))), 0)
            self.assertEqual(db.scalar(select(func.count(AICallCost.id))), 0)
        print("Controlled fixture: confidence=0.60 | low_confidence=True | status=needs_review | cosine=1.0 | automatic_suggestions=0")
        print("Test evidence only: isolated SQLite, simulated vision response, no Gemini requests.")


if __name__ == "__main__":
    unittest.main()
