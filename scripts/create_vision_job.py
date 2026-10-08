import json
from pathlib import Path

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Image, ProcessingJob, Tenant

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    manifest = json.loads(
        (PROJECT_ROOT / "data" / "images.json").read_text(encoding="utf-8")
    )
    corpus_ids = [item["id"] for item in manifest]

    with SessionLocal.begin() as db:
        tenant = db.scalar(
            select(Tenant)
            .where(Tenant.name == "FlyRank Demo")
            .with_for_update()
        )
        if tenant is None:
            raise SystemExit("Demo tenant not found.")

        existing_job = db.scalar(
            select(ProcessingJob).where(
                ProcessingJob.tenant_id == tenant.id,
                ProcessingJob.job_type == "vision",
                ProcessingJob.status.in_(["pending", "queued", "running"]),
            )
        )
        if existing_job is not None:
            print("Active vision job already exists:", existing_job.id)
            print("Status:", existing_job.status)
            return

        pending_count = db.scalar(
            select(func.count())
            .select_from(Image)
            .where(
                Image.tenant_id == tenant.id,
                Image.external_id.in_(corpus_ids),
                Image.processing_status == "pending",
            )
        )
        if pending_count == 0:
            print("No pending corpus images.")
            return

        job = ProcessingJob(
            tenant_id=tenant.id,
            job_type="vision",
            status="pending",
            progress=0,
            retry_count=0,
        )
        db.add(job)
        db.flush()
        job_id = job.id

    print("Vision job saved:", job_id)
    print("Status: pending")
    print("Progress: 0%")
    print("Pending corpus images:", pending_count)


if __name__ == "__main__":
    main()
