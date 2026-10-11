import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import embedding_jobs as service
from app.database import Base, get_db
from app.embedding_vectors import EMBEDDING_DIMENSIONS, EMBEDDING_PROFILE
from app.models import AICallCost, Embedding, Image, ImageMetadata, Post, ProcessingJob, Tenant
from app.routes import jobs
from app.schemas import PostCreate


class EmbeddingJobTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        item = patch.object(service, "SessionLocal", self.sessions)
        item.start()
        self.addCleanup(item.stop)
        self.unit = [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)
        self.image_ids = {"image_1", "image_2"}
        self.sources = [PostCreate(external_id=f"post_{i}", title=f"Title {i}", content=f"Content {i}") for i in (1, 2)]
        with self.sessions.begin() as db:
            db.add_all([Tenant(id=1, name="FlyRank Demo"), Tenant(id=2, name="Other tenant")])
            db.flush()
            for index in (1, 2):
                image = Image(id=index, tenant_id=1, external_id=f"image_{index}", filename="test.jpg",
                              source="test", source_page_url="https://example.com")
                image.image_metadata = ImageMetadata(subject="Red fox", category="Animal", attributes=[],
                                                     caption="A red fox.", confidence=0.99)
                db.add(image)
                db.add(Post(id=index, tenant_id=1, **self.sources[index - 1].model_dump()))

    def add_vector(self, owner, owner_id, tenant_id=1, profile=EMBEDDING_PROFILE, values=None):
        with self.sessions.begin() as db:
            db.add(Embedding(tenant_id=tenant_id, owner_type=owner, owner_id=owner_id,
                             model_name=profile, vector=self.unit if values is None else values))

    def create(self, tenant_id=1):
        return service.create_or_get_embedding_job(tenant_id=tenant_id, image_ids=self.image_ids, post_sources=self.sources)

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

    def test_partial_progress_counts_image_and_post_owners_separately(self):
        self.add_vector("image", 1)
        self.add_vector("post", 1)
        result = self.create()
        self.assertEqual(result.progress, 50)
        self.assertEqual((result.snapshot.image_completed, result.snapshot.post_completed), (1, 1))
        self.assertEqual([(item.owner_type, item.external_id) for item in result.snapshot.pending],
                         [("image", "image_2"), ("post", "post_2")])
        with self.sessions() as db:
            self.assertEqual(db.get(ProcessingJob, result.job_id).job_type, "embedding")
            self.assertEqual(db.scalars(select(AICallCost)).all(), [])

    def test_repeat_creation_reuses_active_job(self):
        first, second = self.create(), self.create()
        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.job_id, second.job_id)
        with self.sessions() as db:
            self.assertEqual(len(db.scalars(select(ProcessingJob)).all()), 1)

    def test_complete_cache_reports_100_but_waits_for_worker(self):
        for owner in ("image", "post"):
            for index in (1, 2):
                self.add_vector(owner, index)
        result = self.create()
        self.assertEqual((result.status, result.progress), ("pending", 100))
        self.assertEqual(result.snapshot.pending, [])

    def test_scientific_probe_is_excluded_from_evaluation_progress(self):
        with self.sessions.begin() as db:
            db.add(Post(id=3, tenant_id=1, external_id="probe_vulpes_vulpes_v1", title="Vulpes vulpes", content="Probe"))
        self.add_vector("post", 3)
        result = self.create()
        self.assertEqual((result.snapshot.post_total, result.snapshot.post_completed), (2, 0))
        self.assertEqual(result.progress, 0)

    def test_other_tenant_vector_and_job_are_not_reused(self):
        self.add_vector("image", 1, tenant_id=2)
        with self.sessions.begin() as db:
            db.add(ProcessingJob(id=1, tenant_id=2, job_type="embedding", status="pending", progress=100))
        result = self.create()
        self.assertEqual(result.progress, 0)
        self.assertNotEqual(result.job_id, 1)
        with self.sessions() as db:
            self.assertEqual(db.get(ProcessingJob, result.job_id).tenant_id, 1)

    def test_old_profile_is_not_counted_as_current_embedding(self):
        self.add_vector("image", 1, profile="old-profile")
        self.assertEqual(self.create().snapshot.image_completed, 0)

    def test_corrupt_or_nonunit_vector_blocks_job_creation(self):
        for values in ([1.0], [2.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)):
            with self.subTest(values_length=len(values)):
                self.add_vector("image", 1, values=values)
                with self.assertRaises(ValueError):
                    self.create()
                with self.sessions.begin() as db:
                    self.assertEqual(db.scalars(select(ProcessingJob)).all(), [])
                    db.delete(db.scalar(select(Embedding)))

    def test_missing_metadata_blocks_job_creation(self):
        with self.sessions.begin() as db:
            db.delete(db.get(Image, 1).image_metadata)
        with self.assertRaises(LookupError):
            self.create()

    def test_changed_post_source_blocks_cached_progress(self):
        with self.sessions.begin() as db:
            db.get(Post, 1).content = "Changed content"
        with self.assertRaises(ValueError):
            self.create()

    def test_manifest_loader_rejects_duplicate_ids(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "data").mkdir()
            (root / "data" / "images.json").write_text(json.dumps([{"id": "same"}, {"id": "same"}]))
            (root / "data" / "eval_posts.json").write_text(json.dumps([{"id": "post", "title": "Title", "content": "Content"}]))
            with self.assertRaises(ValueError):
                service.load_embedding_scope(root)

    def test_existing_job_read_endpoint_returns_embedding_job(self):
        result = self.create()
        response = self.client().get(f"/jobs/{result.job_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["job_type"], "embedding")

    def test_vision_run_one_cannot_queue_embedding_job(self):
        result = self.create()
        with patch.object(jobs, "run_queued_vision_job") as worker:
            response = self.client().post(f"/jobs/{result.job_id}/run-one")
        self.assertEqual(response.status_code, 404)
        worker.assert_not_called()
        with self.sessions() as db:
            self.assertEqual(db.get(ProcessingJob, result.job_id).status, "pending")

    def test_vision_run_one_still_queues_a_vision_job(self):
        with self.sessions.begin() as db:
            job = ProcessingJob(tenant_id=1, job_type="vision", status="pending", progress=0)
            db.add(job)
            db.flush()
            job_id = job.id
        with patch.object(jobs, "run_queued_vision_job") as worker:
            response = self.client().post(f"/jobs/{job_id}/run-one")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "queued")
        worker.assert_called_once_with(job_id)


if __name__ == "__main__":
    unittest.main()
