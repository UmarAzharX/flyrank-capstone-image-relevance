import json
from pathlib import Path

from google.genai import errors
from sqlalchemy import func, select

from app.database import SessionLocal
from app.image_processing import process_image
from app.models import Image, ProcessingJob
from app.retries import call_with_gemini_retries

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_vision_job_once(
    job_id: int,
    *,
    batch_mode: bool = False,
) -> bool:
    manifest = json.loads(
        (PROJECT_ROOT / "data" / "images.json").read_text(encoding="utf-8")
    )
    corpus_ids = {item["id"] for item in manifest}
    total = len(corpus_ids)
    if total == 0:
        raise ValueError("Image manifest is empty.")

    # Claim the job, then commit before calling Gemini.
    with SessionLocal.begin() as db:
        job = db.scalar(
            select(ProcessingJob)
            .where(ProcessingJob.id == job_id)
            .with_for_update()
        )
        if job is None or job.job_type != "vision":
            raise LookupError("Vision job not found.")
        allowed_statuses = (
            {"running"} if batch_mode else {"pending", "queued"}
        )
        if job.status not in allowed_statuses:
            raise ValueError("Job is not ready for this worker.")

        tenant_id = job.tenant_id
        scope = (
            Image.tenant_id == tenant_id,
            Image.external_id.in_(corpus_ids),
        )

        stored_count = db.scalar(
            select(func.count()).select_from(Image).where(*scope)
        )
        if stored_count != total:
            raise ValueError("Some corpus images have not been seeded.")

        completed = db.scalar(
            select(func.count())
            .select_from(Image)
            .where(*scope, Image.image_metadata.has())
        )

        external_id = db.scalar(
            select(Image.external_id)
            .where(
                *scope,
                Image.processing_status == "pending",
                ~Image.image_metadata.has(),
            )
            .order_by(Image.id)
            .limit(1)
        )

        if external_id is None and completed != total:
            raise ValueError("Unprocessed images need state review.")

        job.progress = completed * 100 // total
        job.status = "running" if external_id is not None else "completed"
        job.failure_reason = None

    if external_id is None:
        print("Job already has all corpus metadata. Status: completed")
        return True

    print("Job:", job_id)
    print("Status: running")
    print("Selected image:", external_id)

    def on_retry(next_attempt: int, http_code: int) -> None:
        with SessionLocal.begin() as db:
            job = db.get(ProcessingJob, job_id)
            if job is None or job.status != "running":
                raise RuntimeError("Job is no longer running.")
            job.retry_count += 1

        print(
            f"Retrying image: attempt {next_attempt}/3 "
            f"after HTTP {http_code}"
        )

    try:
        call_with_gemini_retries(
            lambda: process_image(
                tenant_id=tenant_id,
                external_id=external_id,
                job_id=job_id,
            ),
            on_retry=on_retry,
        )
    except Exception as exc:
        reason = (
            f"{external_id}: Gemini HTTP {exc.code}"
            if isinstance(exc, errors.APIError)
            else f"{external_id}: {type(exc).__name__}"
        )
        with SessionLocal.begin() as db:
            job = db.get(ProcessingJob, job_id)
            job.status = "failed"
            job.failure_reason = reason

        print("Status: failed")
        print("Failure:", reason)
        return False

    with SessionLocal.begin() as db:
        completed = db.scalar(
            select(func.count())
            .select_from(Image)
            .where(
                Image.tenant_id == tenant_id,
                Image.external_id.in_(corpus_ids),
                Image.image_metadata.has(),
            )
        )
        job = db.get(ProcessingJob, job_id)
        job.progress = completed * 100 // total
        if completed == total:
            job.status = "completed"
        else:
            job.status = "running" if batch_mode else "pending"
        progress = job.progress
        status = job.status

    print("Image handled:", external_id)
    print("Status:", status)
    print("Corpus progress:", f"{progress}%")
    return True


def run_queued_vision_job(job_id: int) -> None:
    try:
        run_vision_job_once(job_id)
    except Exception as exc:
        reason = f"Worker error: {type(exc).__name__}"
        print(f"Job {job_id}: {reason}")

        try:
            with SessionLocal.begin() as db:
                job = db.scalar(
                    select(ProcessingJob)
                    .where(ProcessingJob.id == job_id)
                    .with_for_update()
                )
                if job is not None and job.status in {"queued", "running"}:
                    job.status = "failed"
                    job.failure_reason = reason
        except Exception as state_error:
            print(
                "Could not save job failure:",
                type(state_error).__name__,
            )