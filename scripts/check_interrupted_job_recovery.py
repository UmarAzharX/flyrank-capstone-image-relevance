import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import AICallCost, Embedding, Image, ImageMetadata, ProcessingJob, Tenant
from app.routes.jobs import router
from scripts.recover_interrupted_job import RECOVERY_REASON, recover_job


class InterruptedJobRecoveryChecks(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        with self.sessions.begin() as db:
            db.add_all([Tenant(id=1, name='FlyRank Demo'), Tenant(id=2, name='Other tenant')])
            db.flush()
            image = Image(id=1, tenant_id=1, external_id='fox_001', filename='fox_001.jpg', source='pexels', source_page_url='https://example.com', processing_status='tagged')
            image.image_metadata = ImageMetadata(subject='Fox', category='Mammal', attributes=['red fur'], caption='Saved fox caption', confidence=.99, low_confidence=False)
            db.add(image)
            db.add(Embedding(id=1, tenant_id=1, owner_type='image', owner_id=1, model_name='fixture-profile', vector=[1.0, 0.0]))
            db.add(ProcessingJob(id=1, tenant_id=1, job_type='vision', status='running', progress=34, retry_count=2))
            db.flush()
            db.add(AICallCost(id=1, tenant_id=1, provider='gemini', model='fixture-model', operation_type='vision', related_job_id=1, related_entity_type='image', related_entity_id=1, usage={'call_outcome': 'response'}, cost_usd=0.0))

    def call(self, **options):
        return recover_job(1, sessions=self.sessions, **options)

    def saved_work(self):
        with self.engine.connect() as connection:
            return {name: connection.execute(select(Base.metadata.tables[name])).all()
                    for name in Base.metadata.tables if name != 'processing_jobs'}

    def test_apply_requires_stopped_worker_confirmation_before_database_access(self):
        sessions = Mock()
        with self.assertRaises(ValueError):
            recover_job(1, apply=True, sessions=sessions)
        sessions.begin.assert_not_called()

    def test_preview_keeps_running_job_and_saved_work(self):
        before = self.saved_work()
        result = self.call()
        self.assertEqual((result.before, result.after, result.changed), ('running', 'running', False))
        with self.sessions() as db:
            self.assertEqual(db.get(ProcessingJob, 1).status, 'running')
        self.assertEqual(before, self.saved_work())

    def test_recovery_preserves_work_progress_and_retries_for_both_worker_types(self):
        before = self.saved_work()
        for job_type in ('vision', 'embedding'):
            for status in ('queued', 'queued_batch', 'running'):
                with self.subTest(job_type=job_type, status=status):
                    with self.sessions.begin() as db:
                        job = db.get(ProcessingJob, 1)
                        job.job_type, job.status, job.failure_reason = job_type, status, None
                        created_at = job.created_at
                    result = self.call(apply=True, workers_stopped=True)
                    self.assertEqual((result.after, result.progress, result.retry_count, result.changed), ('failed', 34, 2, True))
                    with self.sessions() as db:
                        job = db.get(ProcessingJob, 1)
                        self.assertEqual(job.failure_reason, RECOVERY_REASON)
                        self.assertEqual(job.created_at, created_at)
                    self.assertEqual(before, self.saved_work())

    def test_existing_failure_is_reused_without_rewriting_history(self):
        with self.sessions.begin() as db:
            job = db.get(ProcessingJob, 1)
            job.status, job.failure_reason = 'failed', 'Existing budget failure'
        result = self.call(apply=True, workers_stopped=True)
        self.assertFalse(result.changed)
        with self.sessions() as db:
            self.assertEqual(db.get(ProcessingJob, 1).failure_reason, 'Existing budget failure')

    def test_pending_and_completed_jobs_cannot_be_changed(self):
        for status in ('pending', 'completed'):
            with self.sessions.begin() as db:
                db.get(ProcessingJob, 1).status = status
            with self.assertRaises(ValueError):
                self.call(apply=True, workers_stopped=True)
            with self.sessions() as db:
                self.assertEqual(db.get(ProcessingJob, 1).status, status)

    def test_other_tenant_and_unsupported_job_type_are_not_recovered(self):
        for changes in ({'tenant_id': 2}, {'tenant_id': 1, 'job_type': 'unsupported'}):
            with self.sessions.begin() as db:
                job = db.get(ProcessingJob, 1)
                for key, value in changes.items():
                    setattr(job, key, value)
            with self.assertRaises(LookupError):
                self.call(apply=True, workers_stopped=True)
            with self.sessions() as db:
                self.assertEqual(db.get(ProcessingJob, 1).status, 'running')

    def test_existing_resume_api_accepts_recovered_job_without_losing_costs(self):
        before = self.saved_work()
        self.call(apply=True, workers_stopped=True)
        app = FastAPI()
        app.include_router(router)
        def test_db():
            with self.sessions() as db:
                yield db
        app.dependency_overrides[get_db] = test_db
        with patch('google.genai.Client', side_effect=AssertionError('No Gemini in recovery checks.')) as gemini:
            with TestClient(app) as client:
                response = client.post('/jobs/1/resume')
                self.assertEqual(response.status_code, 200)
                self.assertEqual((response.json()['status'], response.json()['progress'], response.json()['retry_count']), ('pending', 34, 2))
                self.assertEqual(client.get('/jobs/1/costs').json()['call_count'], 1)
            gemini.assert_not_called()
        self.assertEqual(before, self.saved_work())


if __name__ == '__main__':
    unittest.main()
