"""Vision-job creation regression checks using isolated SQLite; no AI requests."""
import contextlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import AICallCost, Image, ProcessingJob, Tenant
from scripts import create_vision_job as command


class VisionJobCreationTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "data").mkdir()
        (self.root / "data/images.json").write_text(
            json.dumps([{"id": "fox_001"}]), encoding="utf-8",
        )
        self.engine = create_engine("sqlite:///:memory:")
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        with self.sessions.begin() as db:
            db.add_all([Tenant(id=1, name="FlyRank Demo"), Tenant(id=2, name="Other")])
            db.flush()
            db.add(Image(id=1, tenant_id=1, external_id="fox_001", filename="fox_001.jpg",
                         source="pexels", source_page_url="https://example.com", processing_status="pending"))
        for name, value in (("PROJECT_ROOT", self.root), ("SessionLocal", self.sessions)):
            patcher = patch.object(command, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def invoke(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            command.main()
        return output.getvalue()

    def jobs(self):
        with self.sessions() as db:
            return [(job.id, job.tenant_id, job.job_type, job.status, job.progress, job.retry_count)
                    for job in db.scalars(select(ProcessingJob).order_by(ProcessingJob.id))]

    def test_queued_batch_and_other_active_states_reuse_job_without_changes(self):
        with self.sessions.begin() as db:
            job = ProcessingJob(id=1, tenant_id=1, job_type="vision", status="queued_batch",
                                progress=40, retry_count=2)
            db.add(job)
            db.flush()
            db.add(AICallCost(tenant_id=1, provider="google", model="test", operation_type="vision",
                             related_job_id=1, related_entity_type="image", related_entity_id=1,
                             usage={"call_outcome": "response_received"}, cost_usd=0.0))
        for status in ("queued_batch", "pending", "queued", "running"):
            with self.subTest(status=status):
                with self.sessions.begin() as db:
                    db.get(ProcessingJob, 1).status = status
                before = self.jobs()
                output = self.invoke()
                self.assertIn("Active vision job already exists: 1", output)
                self.assertEqual(self.jobs(), before)
                with self.sessions() as db:
                    self.assertEqual(db.get(Image, 1).processing_status, "pending")
                    self.assertIsNone(db.get(Image, 1).image_metadata)
                    self.assertEqual(len(db.scalars(select(AICallCost)).all()), 1)

    def test_missing_active_job_creates_one_and_repeat_reuses_it(self):
        self.assertIn("Vision job saved:", self.invoke())
        first = self.jobs()
        self.assertEqual(first, [(1, 1, "vision", "pending", 0, 0)])
        self.assertIn("Active vision job already exists:", self.invoke())
        self.assertEqual(self.jobs(), first)
        with self.sessions() as db:
            self.assertEqual(db.scalars(select(AICallCost)).all(), [])

    def test_other_tenant_and_embedding_jobs_do_not_block_demo_vision_job(self):
        with self.sessions.begin() as db:
            db.add_all([
                ProcessingJob(id=1, tenant_id=2, job_type="vision", status="queued_batch", progress=30),
                ProcessingJob(id=2, tenant_id=1, job_type="embedding", status="queued_batch", progress=50),
            ])
        before = self.jobs()
        self.invoke()
        after = self.jobs()
        self.assertEqual(after[:2], before)
        self.assertEqual(after[2], (3, 1, "vision", "pending", 0, 0))

    def test_completed_job_is_preserved_and_new_pending_work_gets_new_job(self):
        with self.sessions.begin() as db:
            db.add(ProcessingJob(id=1, tenant_id=1, job_type="vision", status="completed", progress=100))
        before = self.jobs()
        self.invoke()
        self.assertEqual(self.jobs()[0], before[0])
        self.assertEqual(self.jobs()[1], (2, 1, "vision", "pending", 0, 0))

    def test_pending_images_outside_corpus_do_not_create_job(self):
        with self.sessions.begin() as db:
            db.get(Image, 1).processing_status = "tagged"
            db.add(Image(tenant_id=1, external_id="probe", filename="probe.jpg", source="test",
                         source_page_url="https://example.com", processing_status="pending"))
        self.assertIn("No pending corpus images.", self.invoke())
        self.assertEqual(self.jobs(), [])

    def test_missing_demo_tenant_stops_without_job_creation(self):
        with self.sessions.begin() as db:
            db.delete(db.get(Image, 1))
            db.flush()
            db.delete(db.get(Tenant, 1))
        with self.assertRaisesRegex(SystemExit, "Demo tenant not found"):
            self.invoke()
        self.assertEqual(self.jobs(), [])


if __name__ == "__main__":
    unittest.main()
