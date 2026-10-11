"""Verify probe isolation, cache reuse, and budget failures without AI calls."""

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import post_embeddings
from app.budget import AIUsageLimitError
from app.database import Base
from app.models import Embedding, Post, Tenant
from scripts import prepare_whale_probe as command


class WhaleProbePreparationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        with self.sessions.begin() as db:
            db.add_all([Tenant(id=1, name="FlyRank Demo"), Tenant(id=2, name="Other")])
            db.flush()
            db.add(Post(tenant_id=1, external_id="post_001", title="Original fox title", content="Original fox text"))
        for module in (command, post_embeddings):
            p = patch.object(module, "SessionLocal", self.sessions)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(post_embeddings, "generate_text_embedding", return_value=[1.0] + [0.0] * 767)
        self.generator = p.start()
        self.addCleanup(p.stop)
        self.case = {"id": "guard_003", "case_type": "no_suitable_image",
                     "post_title": "How Humpback Whales Migrate Across Oceans",
                     "post_content": "Humpback whales travel between feeding and breeding grounds."}

    def test_repeat_reuses_vector_and_leaves_evaluation_post_unchanged(self):
        first = command.prepare_probe(self.case)
        second = command.prepare_probe(self.case)
        self.assertTrue(first[2])
        self.assertFalse(second[2])
        self.assertEqual(first[:2], second[:2])
        self.generator.assert_called_once()
        self.assertEqual(self.generator.call_args.kwargs["owner_id"], first[0])
        with self.sessions() as db:
            original = db.scalar(select(Post).where(Post.external_id == "post_001"))
            self.assertEqual((original.title, original.content), ("Original fox title", "Original fox text"))

    def test_changed_text_cannot_reuse_stale_embedding(self):
        command.prepare_probe(self.case)
        self.generator.reset_mock()
        changed = {**self.case, "post_content": "Changed whale content"}
        with self.assertRaises(ValueError):
            command.prepare_probe(changed)
        self.generator.assert_not_called()

    def test_budget_failure_leaves_no_vector_and_can_be_retried(self):
        self.generator.side_effect = AIUsageLimitError("AI call limit reached.")
        with self.assertRaises(AIUsageLimitError):
            command.prepare_probe(self.case)
        with self.sessions() as db:
            self.assertIsNone(db.scalar(select(Embedding)))
        self.generator.side_effect = None
        result = command.prepare_probe(self.case)
        self.assertTrue(result[2])

    def test_other_tenant_probe_is_not_reused_or_changed(self):
        with self.sessions.begin() as db:
            db.add(Post(tenant_id=2, external_id=command.PROBE_ID, title="Other", content="Other"))
        result = command.prepare_probe(self.case)
        with self.sessions() as db:
            own = db.get(Post, result[0])
            self.assertEqual(own.tenant_id, 1)
            other = db.scalar(select(Post).where(Post.tenant_id == 2))
            self.assertEqual((other.title, other.content), ("Other", "Other"))


if __name__ == "__main__":
    unittest.main()
