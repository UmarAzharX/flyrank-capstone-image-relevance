from sqlalchemy import select

from app.database import SessionLocal
from app.models import AICallCost, Image, ProcessingJob, Tenant

JOB_ID = 1
VERIFIED_CALLS = {
    4: "fox_003",
    5: "fox_004",
    6: "fox_005",
}


def main() -> None:
    updated = 0
    already_linked = 0

    with SessionLocal.begin() as db:
        job = db.scalar(
            select(ProcessingJob)
            .join(Tenant)
            .where(
                ProcessingJob.id == JOB_ID,
                ProcessingJob.job_type == "vision",
                Tenant.name == "FlyRank Demo",
            )
            .with_for_update()
        )
        if job is None:
            raise SystemExit("Demo vision job not found.")

        if job.status in {"queued", "running"}:
            raise SystemExit("Wait until the worker step finishes.")

        for cost_id, expected_image in VERIFIED_CALLS.items():
            cost = db.scalar(
                select(AICallCost)
                .where(AICallCost.id == cost_id)
                .with_for_update()
            )
            if cost is None:
                raise SystemExit(f"Cost record {cost_id} not found.")

            image = db.get(Image, cost.related_entity_id)

            matches = (
                cost.tenant_id == job.tenant_id
                and cost.provider == "google"
                and cost.model == "gemini-3.5-flash-lite"
                and cost.operation_type == "vision"
                and cost.related_entity_type == "image"
                and image is not None
                and image.tenant_id == job.tenant_id
                and image.external_id == expected_image
            )
            if not matches:
                raise SystemExit(
                    f"Cost record {cost_id} failed verification."
                )

            if cost.related_job_id == JOB_ID:
                already_linked += 1
            elif cost.related_job_id is None:
                cost.related_job_id = JOB_ID
                updated += 1
            else:
                raise SystemExit(
                    f"Cost record {cost_id} belongs to another job."
                )

    print("Records linked:", updated)
    print("Already linked:", already_linked)


if __name__ == "__main__":
    main()