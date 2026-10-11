"""Offline workflow checks with synthetic vectors, not semantic-model evidence."""
import math
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import post_embeddings, ranking
from app.budget import AIUsageLimitError
from app.database import Base
from app.embedding_vectors import EMBEDDING_DIMENSIONS, EMBEDDING_PROFILE
from app.models import Embedding, Image, ImageMetadata, Post, Tenant
from scripts import probe_equivalent_concepts as probe


def vector(score):
    return [score, math.sqrt(1 - score * score)] + [0.0] * (EMBEDDING_DIMENSIONS - 2)


class EquivalentConceptProbeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.addCleanup(self.engine.dispose)
        for module in (probe, post_embeddings, ranking):
            patcher = patch.object(module, "SessionLocal", self.sessions)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.generator = patch.object(post_embeddings, "generate_text_embedding", return_value=vector(1.0)).start()
        self.addCleanup(patch.stopall)
        self.corpus_ids = {"fox_001", "wolf_001", "dog_001"}
        with self.sessions.begin() as db:
            db.add(Tenant(id=1, name="FlyRank Demo"))
            db.flush()
            db.add(Post(id=1, tenant_id=1, external_id="post_001", title="Original post", content="Original content"))
            for index, (external_id, subject, score) in enumerate((
                ("fox_001", "Red fox", 0.90),
                ("wolf_001", "Gray wolf", 0.80),
                ("dog_001", "Siberian Husky", 0.75),
            ), start=1):
                image = Image(id=index, tenant_id=1, external_id=external_id,
                              filename="test.jpg", source="test", source_page_url="https://example.com")
                image.image_metadata = ImageMetadata(
                    subject=subject, category="Animal", attributes=["close-up"],
                    caption=f"A close-up portrait of a {subject}.", confidence=0.99,
                )
                db.add(image)
                db.add(Embedding(tenant_id=1, owner_type="image", owner_id=index,
                                 model_name=EMBEDDING_PROFILE, vector=vector(score)))

    def run_probe(self):
        with patch.object(probe.settings, "similarity_threshold", 0.70), patch.object(probe.settings, "vision_confidence_threshold", 0.80):
            return probe.run_probe(self.corpus_ids)

    def test_separate_fixture_uses_scientific_name_without_english_animal_alias(self):
        report = self.run_probe()
        self.assertNotIn("fox", report["embedding_input"].lower())
        self.assertIn("Vulpes vulpes", report["embedding_input"])
        self.assertTrue(report["passed"])
        self.assertEqual(report["candidates_checked"], 3)
        with self.sessions() as db:
            original = db.scalar(select(Post).where(Post.external_id == "post_001"))
            self.assertEqual((original.title, original.content), ("Original post", "Original content"))

    def test_production_embedding_path_receives_probe_text_and_owner(self):
        self.run_probe()
        kwargs = self.generator.call_args.kwargs
        self.assertEqual(kwargs["owner_type"], "post")
        self.assertEqual(kwargs["tenant_id"], 1)
        self.assertIn("Vulpes vulpes", kwargs["text"])
        self.assertNotIn("fox", kwargs["text"].lower())
        with self.sessions() as db:
            stored = db.scalar(select(Post).where(Post.external_id == probe.PROBE_ID))
            self.assertEqual(kwargs["owner_id"], stored.id)

    def test_repeat_probe_reuses_embedding_without_another_generation(self):
        first = self.run_probe()
        second = self.run_probe()
        self.assertTrue(first["embedding_created"])
        self.assertFalse(second["embedding_created"])
        self.assertEqual(first["embedding_id"], second["embedding_id"])
        self.generator.assert_called_once()

    def test_conflicting_saved_text_blocks_stale_embedding_reuse(self):
        with self.sessions.begin() as db:
            db.add(Post(tenant_id=1, external_id=probe.PROBE_ID, title="Changed", content="Changed"))
        with self.assertRaises(ValueError):
            self.run_probe()
        self.generator.assert_not_called()

    def test_budget_block_propagates_without_creating_embedding(self):
        self.generator.side_effect = AIUsageLimitError("AI call limit reached.")
        with self.assertRaises(AIUsageLimitError):
            self.run_probe()
        with self.sessions() as db:
            self.assertEqual(db.scalars(select(Embedding).where(Embedding.owner_type == "post")).all(), [])

    def test_high_scoring_wolf_still_rejected_with_subject_reason(self):
        report = self.run_probe()
        wolf = report["highest_scoring_wolf"]
        self.assertEqual(wolf["subject_decision"], "reject")
        self.assertEqual(wolf["guard_decision"], "reject")
        self.assertIn("post describes fox; image describes wolf", wolf["explanation"])

    def test_filtered_fox_win_does_not_hide_raw_wolf_win(self):
        with self.sessions.begin() as db:
            wolf = db.scalar(select(Embedding).where(Embedding.owner_type == "image", Embedding.owner_id == 2))
            wolf.vector = vector(1.0)
        report = self.run_probe()
        self.assertFalse(report["checks"]["raw_top_1_is_fox"])
        self.assertFalse(report["checks"]["fox_scores_above_best_wolf"])
        self.assertTrue(report["checks"]["eligible_top_1_is_fox"])
        self.assertFalse(report["passed"])

    def test_missing_wolf_cannot_count_as_rejection_evidence(self):
        ranked = ranking.rank_images_for_post
        self.run_probe()
        only_fox = ranked(tenant_id=1, external_id=probe.PROBE_ID, corpus_ids={"fox_001"}, top_k=1)
        _, wolf, checks = probe.inspect_ranking(only_fox)
        self.assertIsNone(wolf)
        self.assertFalse(checks["all_wolves_rejected_by_subject"])


if __name__ == "__main__":
    unittest.main()
