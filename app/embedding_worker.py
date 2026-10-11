from time import sleep

from google.genai import errors
from sqlalchemy import select

from app.database import SessionLocal
from app.embedding_jobs import EMBEDDING_JOB_TYPE, embedding_snapshot, load_embedding_scope
from app.image_embeddings import embed_image
from app.models import ProcessingJob
from app.post_embeddings import embed_post
from app.retries import call_with_gemini_retries


def _scoped_running_job(db, job_id, tenant_id):
    job = db.scalar(select(ProcessingJob).where(
        ProcessingJob.id == job_id, ProcessingJob.tenant_id == tenant_id,
        ProcessingJob.job_type == EMBEDDING_JOB_TYPE,
    ).with_for_update())
    if job is None or job.status != "running":
        raise RuntimeError("Embedding job is no longer running.")
    return job


def run_embedding_batch(job_id: int, *, max_steps: int = 3,
                        pause_seconds: int = 15, queued: bool = False) -> bool:
    if type(max_steps) is not int or not 1 <= max_steps <= 60:
        raise ValueError("max_steps must be between 1 and 60.")
    if type(pause_seconds) is not int or not 0 <= pause_seconds <= 60:
        raise ValueError("pause_seconds must be between 0 and 60.")
    # Claim once and commit before any provider request. A second dispatch cannot
    # claim a running job. SQLite tests do not prove PostgreSQL row-lock behavior.
    with SessionLocal.begin() as db:
        job = db.scalar(select(ProcessingJob).where(
            ProcessingJob.id == job_id, ProcessingJob.job_type == EMBEDDING_JOB_TYPE,
        ).with_for_update())
        if job is None:
            raise LookupError("Embedding job not found.")
        if job.status == "completed":
            return True
        if job.status != ("queued_batch" if queued else "pending"):
            raise ValueError("Embedding job is not ready for this worker.")
        tenant_id = job.tenant_id
        job.status = "running"
        job.failure_reason = None

    try:
        image_ids, post_sources = load_embedding_scope()

        def snapshot_and_update():
            with SessionLocal.begin() as db:
                job = _scoped_running_job(db, job_id, tenant_id)
                snapshot = embedding_snapshot(db, tenant_id=tenant_id, image_ids=image_ids,
                                              post_sources=post_sources)
                job.progress = snapshot.progress
                if not snapshot.pending:
                    job.status = "completed"
                return snapshot

        def on_retry(next_attempt, http_code):
            with SessionLocal.begin() as db:
                job = _scoped_running_job(db, job_id, tenant_id)
                job.retry_count += 1
            print(f"Embedding job {job_id}: retry {next_attempt}/3 after HTTP {http_code}")

        snapshot = snapshot_and_update()
        if not snapshot.pending:
            print(f"Embedding job {job_id}: completed, progress 100%. Saved vectors reused; no Gemini request sent.")
            return True
        for step in range(1, max_steps + 1):
            item = snapshot.pending[0]
            operation = embed_image if item.owner_type == "image" else embed_post
            print(f"Embedding job {job_id}: step {step}/{max_steps}, {item.owner_type}={item.external_id}")
            call_with_gemini_retries(
                lambda: operation(tenant_id=tenant_id, external_id=item.external_id, job_id=job_id),
                on_retry=on_retry,
            )
            snapshot = snapshot_and_update()
            print(f"Embedding job {job_id}: progress {snapshot.progress}%")
            if not snapshot.pending:
                print(f"Embedding job {job_id}: completed.")
                return True
            if step < max_steps and pause_seconds:
                sleep(pause_seconds)
        with SessionLocal.begin() as db:
            job = _scoped_running_job(db, job_id, tenant_id)
            job.status = "pending"
        print(f"Embedding job {job_id}: step limit reached; pending at {snapshot.progress}%.")
        return True
    except Exception as exc:
        # Persist useful type/status information without provider or connection text.
        reason = f"Embedding worker error: {type(exc).__name__}"
        if isinstance(exc, errors.APIError):
            reason += f" (HTTP {exc.code})"
        with SessionLocal.begin() as db:
            job = db.scalar(select(ProcessingJob).where(
                ProcessingJob.id == job_id, ProcessingJob.tenant_id == tenant_id,
                ProcessingJob.job_type == EMBEDDING_JOB_TYPE,
            ).with_for_update())
            if job is not None and job.status == "running":
                job.status = "failed"
                job.failure_reason = reason
        print(f"Embedding job {job_id}: failed. {reason}")
        return False


def run_queued_embedding_batch(job_id: int, *, max_steps: int, pause_seconds: int):
    try:
        run_embedding_batch(job_id, max_steps=max_steps, pause_seconds=pause_seconds, queued=True)
    except Exception as exc:
        reason = f"Background embedding error: {type(exc).__name__}"
        print(f"Embedding job {job_id}: {reason}")
        try:
            with SessionLocal.begin() as db:
                job = db.scalar(select(ProcessingJob).where(
                    ProcessingJob.id == job_id, ProcessingJob.job_type == EMBEDDING_JOB_TYPE,
                ).with_for_update())
                # Avoid changing a running job that this invocation failed to claim.
                if job is not None and job.status == "queued_batch":
                    job.status = "failed"
                    job.failure_reason = reason
        except Exception as state_error:
            print("Could not save embedding failure:", type(state_error).__name__)
