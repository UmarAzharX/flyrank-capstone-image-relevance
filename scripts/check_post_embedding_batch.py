from contextlib import redirect_stdout
from io import StringIO
import unittest
from unittest.mock import patch

from google.genai import errors
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import post_embedding_batch as batch
from app import post_embeddings
from app.budget import AIUsageLimitError
from app.database import Base
from app.embedding_vectors import EMBEDDING_DIMENSIONS, EMBEDDING_PROFILE
from app.models import Embedding, Post, Tenant


def api_error(code):
    return errors.APIError(code, {"error": {"message": "Controlled error"}})


class PostEmbeddingBatchTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        with self.sessions.begin() as db:
            db.add_all([Tenant(id=1, name="FlyRank Demo"), Tenant(id=2, name="Other tenant")])
        for module in (batch, post_embeddings):
            self.start_patch(patch.object(module, "SessionLocal", self.sessions))
        self.generator = self.start_patch(patch.object(post_embeddings, "generate_text_embedding"))
        self.retry_sleep = self.start_patch(patch("app.retries.sleep"))
        self.pause = self.start_patch(patch.object(batch, "sleep"))
        self.unit = [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)
        self.generator.return_value = self.unit
        self.sources = [{"id": f"post_{i}", "title": f"Post {i}", "content": f"Content {i}"} for i in range(1, 4)]

    def start_patch(self, item):
        result = item.start()
        self.addCleanup(item.stop)
        return result

    def run_batch(self, steps=3, sources=None):
        with redirect_stdout(StringIO()):
            return batch.run_post_embedding_batch(sources=self.sources if sources is None else sources,
                                                 max_steps=steps, pause_seconds=15)

    def test_transient_error_retries_then_persists_once(self):
        self.generator.side_effect = [api_error(503), self.unit]
        self.assertEqual(self.run_batch(1), (1, 3))
        self.assertEqual(self.generator.call_count, 2)
        self.retry_sleep.assert_called_once_with(2)
        with self.sessions() as db:
            self.assertEqual(len(db.scalars(select(Embedding)).all()), 1)

    def test_retry_limit_stops_without_partial_embedding(self):
        self.generator.side_effect = api_error(503)
        with self.assertRaises(errors.APIError):
            self.run_batch(1)
        self.assertEqual(self.generator.call_count, 3)
        self.assertEqual([item.args[0] for item in self.retry_sleep.call_args_list], [2, 4])
        with self.sessions() as db:
            self.assertEqual(db.scalars(select(Embedding)).all(), [])

    def test_permanent_error_is_not_retried(self):
        self.generator.side_effect = api_error(400)
        with self.assertRaises(errors.APIError):
            self.run_batch(1)
        self.generator.assert_called_once()
        self.retry_sleep.assert_not_called()

    def test_budget_error_is_not_retried(self):
        self.generator.side_effect = AIUsageLimitError("AI call limit reached.")
        with self.assertRaises(AIUsageLimitError):
            self.run_batch(1)
        self.generator.assert_called_once()
        self.retry_sleep.assert_not_called()

    def test_bounded_runs_resume_and_completed_run_sends_no_requests(self):
        self.assertEqual(self.run_batch(1), (1, 3))
        self.assertEqual(self.run_batch(1), (2, 3))
        self.assertEqual(self.run_batch(1), (3, 3))
        self.assertEqual(self.run_batch(1), (3, 3))
        self.assertEqual(self.generator.call_count, 3)
        self.pause.assert_not_called()

    def test_pause_occurs_between_selected_posts_only(self):
        self.assertEqual(self.run_batch(2), (2, 3))
        self.pause.assert_called_once_with(15)

    def test_changed_saved_post_blocks_generation_and_cached_reuse(self):
        self.run_batch(1)
        self.generator.reset_mock()
        with self.sessions.begin() as db:
            post = db.scalar(select(Post).where(Post.tenant_id == 1, Post.external_id == "post_1"))
            post.content = "Edited after embedding"
        with self.assertRaises(ValueError):
            self.run_batch()
        self.generator.assert_not_called()

    def test_other_tenant_vector_does_not_count_as_demo_completion(self):
        with self.sessions.begin() as db:
            other = Post(tenant_id=2, external_id="post_1", title="Private title", content="Private content")
            db.add(other)
            db.flush()
            db.add(Embedding(tenant_id=2, owner_type="post", owner_id=other.id,
                             model_name=EMBEDDING_PROFILE, vector=self.unit))
        self.assertEqual(self.run_batch(1), (1, 3))
        self.generator.assert_called_once()
        self.assertEqual(self.generator.call_args.kwargs["tenant_id"], 1)

    def test_invalid_batch_and_duplicate_sources_send_no_requests(self):
        for steps in (0, 11, True):
            with self.subTest(steps=steps), self.assertRaises(ValueError):
                self.run_batch(steps)
        for sources in ([], [self.sources[0], self.sources[0]]):
            with self.subTest(sources=sources), self.assertRaises(ValueError):
                self.run_batch(sources=sources)
        self.generator.assert_not_called()


if __name__ == "__main__":
    unittest.main()
