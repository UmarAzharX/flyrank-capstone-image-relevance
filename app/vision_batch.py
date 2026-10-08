from time import sleep

from sqlalchemy import select

from app.database import SessionLocal
from app.models import ProcessingJob
from app.vision_worker import run_vision_job_once


def _job_state(job_id: int) -> tuple[str, int]:
    with SessionLocal() as db:
        job = db.get(ProcessingJob, job_id)
        if job is None or job.job_type != "vision":
            raise LookupError("Vision job not found.")
        return job.status, job.progress


def run_vision_batch(
    job_id: int,
    *,
    max_steps: int = 3,
    pause_seconds: int = 15,
    queued: bool = False,
) -> bool:
    if not 1 <= max_steps <= 50:
        raise ValueError("max_steps must be between 1 and 50.")
    if not 0 <= pause_seconds <= 60:
        raise ValueError("pause_seconds must be between 0 and 60.")

    # Claim the whole batch before starting any image.
    with SessionLocal.begin() as db:
        job = db.scalar(
            select(ProcessingJob)
            .where(ProcessingJob.id == job_id)
            .with_for_update()
        )
        if job is None or job.job_type != "vision":
            raise LookupError("Vision job not found.")

        if job.status == "completed":
            print("Corpus processing already completed.")
            return True

        expected_status = "queued_batch" if queued else "pending"
        if job.status != expected_status:
            raise ValueError("Job is not ready for this batch runner.")

        job.status = "running"
        job.failure_reason = None

    failure_reason = None

    try:
        for step in range(1, max_steps + 1):
            print(f"Batch step: {step}/{max_steps}")

            if not run_vision_job_once(job_id, batch_mode=True):
                print("Batch stopped after a worker failure.")
                return False

            status, progress = _job_state(job_id)

            if status == "completed":
                print("Corpus processing completed.")
                return True

            if status != "running":
                print("Batch stopped. Job status:", status)
                return False

            if step < max_steps:
                print(
                    f"Waiting {pause_seconds} seconds "
                    "before the next image."
                )
                sleep(pause_seconds)

        print("Batch step limit reached.")
        return True

    except Exception as exc:
        failure_reason = f"Batch error: {type(exc).__name__}"
        raise

    finally:
        # Release the batch while preserving completed/failed states.
        with SessionLocal.begin() as db:
            job = db.scalar(
                select(ProcessingJob)
                .where(ProcessingJob.id == job_id)
                .with_for_update()
            )
            if job is not None and job.status == "running":
                job.status = "failed" if failure_reason else "pending"
                job.failure_reason = failure_reason

        status, progress = _job_state(job_id)
        print("Job status:", status)
        print("Corpus progress:", f"{progress}%")


def run_queued_vision_batch(
    job_id: int,
    *,
    max_steps: int,
    pause_seconds: int,
) -> None:
    try:
        run_vision_batch(
            job_id,
            max_steps=max_steps,
            pause_seconds=pause_seconds,
            queued=True,
        )
    except Exception as exc:
        reason = f"Background batch error: {type(exc).__name__}"
        print(f"Job {job_id}: {reason}")

        try:
            with SessionLocal.begin() as db:
                job = db.scalar(
                    select(ProcessingJob)
                    .where(ProcessingJob.id == job_id)
                    .with_for_update()
                )
                if (
                    job is not None
                    and job.job_type == "vision"
                    and job.status == "queued_batch"
                ):
                    job.status = "failed"
                    job.failure_reason = reason
        except Exception as state_error:
            print(
                "Could not save batch failure:",
                type(state_error).__name__,
            )