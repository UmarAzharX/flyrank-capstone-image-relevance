from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.genai import errors
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import embedding_client, embedding_costs, embedding_jobs, embedding_worker as worker
from app import image_embeddings, post_embeddings
from app.database import Base, get_db
from app.embedding_vectors import EMBEDDING_DIMENSIONS, EMBEDDING_PROFILE
from app.models import AICallCost, Embedding, Image, ImageMetadata, Post, ProcessingJob, Tenant
from app.routes import jobs
from app.schemas import PostCreate


def api_error(code):
    return errors.APIError(code, {"error": {"message": "PRIVATE simulated provider text"}})


class EmbeddingWorkerTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)

        @event.listens_for(self.engine, "connect")
        def advisory_lock_stub(connection, record):
            # Execute production reservation logic; this stub does not emulate
            # PostgreSQL concurrency or prove row/advisory lock semantics.
            connection.create_function("pg_advisory_xact_lock", 2, lambda *args: 0)

        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        for module in (worker, embedding_jobs, embedding_costs, image_embeddings, post_embeddings):
            self.start_patch(patch.object(module, "SessionLocal", self.sessions))
        self.start_patch(patch.object(embedding_costs.settings, "ai_max_calls", 100))
        self.start_patch(patch.object(embedding_costs.settings, "ai_budget_usd", 0.0))
        self.retry_sleep = self.start_patch(patch("app.retries.sleep"))
        self.pause = self.start_patch(patch.object(worker, "sleep"))
        self.unit = [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)
        self.response = SimpleNamespace(metadata=None, embeddings=[SimpleNamespace(values=self.unit, statistics=None)])
        self.client_factory = self.start_patch(patch.object(embedding_client, "create_gemini_client"))
        self.fake_client = MagicMock()
        self.client_factory.return_value.__enter__.return_value = self.fake_client
        self.sdk = self.fake_client.models.embed_content
        self.sdk.return_value = self.response
        self.source = PostCreate(external_id="post", title="A red fox close-up", content="A close-up portrait of a red fox.")
        self.start_patch(patch.object(worker, "load_embedding_scope", return_value=({"fox"}, [self.source])))
        with self.sessions.begin() as db:
            db.add_all([Tenant(id=1, name="FlyRank Demo"), Tenant(id=2, name="Other tenant")])
            db.flush()
            for index in (1, 2):
                image = Image(id=index, tenant_id=index, external_id="fox", filename="test.jpg",
                              source="test", source_page_url="https://example.com")
                image.image_metadata = ImageMetadata(subject="Red fox", category="Animal", attributes=["close-up"],
                                                     caption="A close-up portrait of a red fox.", confidence=0.99)
                db.add(image)
                db.add(Post(id=index, tenant_id=index, **self.source.model_dump()))
            db.add_all([
                ProcessingJob(id=1, tenant_id=1, job_type="embedding", status="pending", progress=0),
                ProcessingJob(id=2, tenant_id=2, job_type="embedding", status="pending", progress=0),
                ProcessingJob(id=3, tenant_id=1, job_type="vision", status="pending", progress=0),
            ])

    def start_patch(self, item):
        result = item.start()
        self.addCleanup(item.stop)
        return result

    def run_batch(self, steps=2, job_id=1):
        with redirect_stdout(StringIO()):
            return worker.run_embedding_batch(job_id, max_steps=steps, pause_seconds=15)

    def job_state(self):
        with self.sessions() as db:
            job = db.get(ProcessingJob, 1)
            return job.status, job.progress, job.retry_count, job.failure_reason

    def cached_vectors(self):
        with self.sessions.begin() as db:
            for owner in ("image", "post"):
                db.add(Embedding(tenant_id=1, owner_type=owner, owner_id=1,
                                 model_name=EMBEDDING_PROFILE, vector=self.unit))

    def ledger(self):
        with self.sessions() as db:
            return [(row.related_job_id, row.related_entity_type, row.related_entity_id,
                     row.usage["call_outcome"], row.cost_usd)
                    for row in db.scalars(select(AICallCost).order_by(AICallCost.id)).all()]

    def client(self):
        app = FastAPI()
        app.include_router(jobs.router)

        def test_db():
            with self.sessions() as db:
                yield db

        app.dependency_overrides[get_db] = test_db
        client = TestClient(app)
        self.addCleanup(client.close)
        return client

    def dispatch(self, client=None, job_id=1, **params):
        with redirect_stdout(StringIO()):
            return (client or self.client()).post(f"/jobs/{job_id}/run-embeddings",
                                                  params={"max_steps": 2, "pause_seconds": 0, **params})

    def test_cached_job_completes_without_sdk_or_cost_records(self):
        self.cached_vectors()
        self.assertTrue(self.run_batch())
        self.assertEqual(self.job_state(), ("completed", 100, 0, None))
        self.client_factory.assert_not_called()
        self.assertEqual(self.ledger(), [])

    def test_bounded_job_resumes_from_persisted_progress(self):
        self.assertTrue(self.run_batch(1))
        self.assertEqual(self.job_state()[:3], ("pending", 50, 0))
        self.assertTrue(self.run_batch(1))
        self.assertEqual(self.job_state()[:3], ("completed", 100, 0))
        self.assertEqual([row[:3] for row in self.ledger()], [(1, "image", 1), (1, "post", 1)])
        self.pause.assert_not_called()

    def test_transient_retry_is_persisted_and_each_call_attributed(self):
        self.sdk.side_effect = [api_error(503), self.response, self.response]
        self.assertTrue(self.run_batch())
        self.assertEqual(self.job_state()[:3], ("completed", 100, 1))
        self.assertEqual([row[3] for row in self.ledger()], ["api_error", "response_received", "response_received"])
        self.assertEqual([row[0] for row in self.ledger()], [1, 1, 1])
        self.retry_sleep.assert_called_once_with(2)

    def test_exhausted_retries_fail_with_safe_reason(self):
        self.sdk.side_effect = api_error(503)
        self.assertFalse(self.run_batch())
        status, progress, retries, reason = self.job_state()
        self.assertEqual((status, progress, retries), ("failed", 0, 2))
        self.assertIn("HTTP 503", reason)
        self.assertNotIn("PRIVATE", reason)
        self.assertEqual(len(self.ledger()), 3)

    def test_permanent_error_stops_after_one_call(self):
        self.sdk.side_effect = api_error(400)
        self.assertFalse(self.run_batch())
        self.assertEqual(self.job_state()[:3], ("failed", 0, 0))
        self.sdk.assert_called_once()
        self.retry_sleep.assert_not_called()

    def test_budget_block_prevents_sdk_and_cost_record(self):
        with patch.object(embedding_costs.settings, "ai_max_calls", 0):
            self.assertFalse(self.run_batch())
        self.assertEqual(self.job_state()[0], "failed")
        self.assertIn("AIUsageLimitError", self.job_state()[3])
        self.client_factory.assert_not_called()
        self.assertEqual(self.ledger(), [])

    def test_retry_cannot_bypass_call_cap(self):
        self.sdk.side_effect = api_error(503)
        with patch.object(embedding_costs.settings, "ai_max_calls", 1):
            self.assertFalse(self.run_batch())
        self.assertEqual(self.job_state()[:3], ("failed", 0, 1))
        self.assertIn("AIUsageLimitError", self.job_state()[3])
        self.sdk.assert_called_once()
        self.assertEqual(len(self.ledger()), 1)

    def test_invalid_vector_fails_without_storing_embedding(self):
        self.sdk.return_value = SimpleNamespace(metadata=None, embeddings=[SimpleNamespace(values=[1.0], statistics=None)])
        self.assertFalse(self.run_batch())
        self.assertIn("ValueError", self.job_state()[3])
        self.assertEqual(len(self.ledger()), 1)
        with self.sessions() as db:
            self.assertEqual(db.scalars(select(Embedding)).all(), [])

    def test_background_endpoint_accepts_and_completes_cached_job(self):
        self.cached_vectors()
        client = self.client()
        response = self.dispatch(client)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "queued_batch")
        self.assertEqual(client.get("/jobs/1").json()["status"], "completed")
        costs = client.get("/jobs/1/costs").json()
        self.assertEqual((costs["call_count"], costs["cost_usd"]), (0, 0.0))
        self.client_factory.assert_not_called()

    def test_wrong_tenant_and_vision_job_are_not_dispatched(self):
        for job_id in (2, 3, 999):
            with self.subTest(job_id=job_id):
                self.assertEqual(self.dispatch(job_id=job_id).status_code, 404)
        self.client_factory.assert_not_called()

    def test_duplicate_queue_attempt_returns_conflict(self):
        with self.sessions.begin() as db:
            db.get(ProcessingJob, 1).status = "queued_batch"
        self.assertEqual(self.dispatch().status_code, 409)
        self.client_factory.assert_not_called()

    def test_invalid_dispatch_parameters_do_not_run_worker(self):
        for params in ({"max_steps": 0}, {"max_steps": 61}, {"pause_seconds": -1}, {"pause_seconds": 61}):
            with self.subTest(params=params):
                self.assertEqual(self.dispatch(**params).status_code, 422)
        self.assertEqual(self.dispatch(job_id=0).status_code, 422)
        self.client_factory.assert_not_called()

    def test_failed_job_can_resume_and_keeps_retry_history(self):
        self.sdk.side_effect = api_error(503)
        self.assertFalse(self.run_batch())
        client = self.client()
        response = client.post("/jobs/1/resume")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "pending")
        self.assertEqual(response.json()["retry_count"], 2)
        self.sdk.side_effect = None
        self.assertEqual(self.dispatch(client).status_code, 202)
        self.assertEqual(self.job_state()[:3], ("completed", 100, 2))
        self.assertEqual(len(self.ledger()), 5)

    def test_failed_job_resume_conflicts_with_another_active_embedding_job(self):
        with self.sessions.begin() as db:
            db.get(ProcessingJob, 1).status = "failed"
            db.add(ProcessingJob(id=4, tenant_id=1, job_type="embedding", status="pending", progress=0))
        response = self.client().post("/jobs/1/resume")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.job_state()[0], "failed")
        self.client_factory.assert_not_called()

    def test_completed_dispatch_is_conflict_without_new_call(self):
        self.cached_vectors()
        self.run_batch()
        self.assertEqual(self.dispatch().status_code, 409)
        self.assertEqual(self.ledger(), [])

    def test_worker_cannot_claim_wrong_type_or_running_job(self):
        with self.assertRaises(LookupError):
            self.run_batch(job_id=3)
        with self.sessions.begin() as db:
            db.get(ProcessingJob, 1).status = "running"
        with self.assertRaises(ValueError):
            self.run_batch()
        self.client_factory.assert_not_called()

    def test_reservation_rejects_other_tenant_job_context(self):
        with self.sessions.begin() as db:
            db.get(ProcessingJob, 2).status = "running"
        with self.assertRaises(LookupError):
            embedding_costs.reserve_free_tier_embedding_call(tenant_id=1, owner_type="image", owner_id=1, job_id=2)
        self.assertEqual(self.ledger(), [])


if __name__ == "__main__":
    unittest.main()
