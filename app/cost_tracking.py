from sqlalchemy import func, select

from app.budget import check_ai_limits
from app.config import settings
from app.database import SessionLocal
from app.models import AICallCost, Image, ProcessingJob


def record_free_tier_vision_call(
    *,
    tenant_id: int,
    image_id: int,
    model: str,
    usage: dict[str, object] | None,
    job_id: int | None = None,
) -> int:
    if model != "gemini-3.5-flash-lite":
        raise ValueError("Free-tier pricing has not been configured for this model.")

    with SessionLocal.begin() as db:
        image = db.scalar(
            select(Image).where(
                Image.id == image_id,
                Image.tenant_id == tenant_id,
            )
        )
        if image is None:
            raise ValueError("Image not found for this tenant.")

        if job_id is not None:
            job = db.scalar(
                select(ProcessingJob).where(
                    ProcessingJob.id == job_id,
                    ProcessingJob.tenant_id == tenant_id,
                    ProcessingJob.job_type == "vision",
                )
            )
            if job is None:
                raise ValueError("Vision job not found for this tenant.")

        cost_record = AICallCost(
            tenant_id=tenant_id,
            provider="google",
            model=model,
            operation_type="vision",
            related_job_id=job_id,
            related_entity_type="image",
            related_entity_id=image_id,
            usage={
                **(usage or {}),
                "usage_available": bool(
                    usage is not None and usage.get("usage_available", True)
                ),
                "call_outcome": (usage or {}).get(
                    "call_outcome", "response_received"
                ),
                "billing_tier": "free",
                "cost_basis": "free_tier_pricing",
            },
            cost_usd=0.0,
        )

        db.add(cost_record)
        db.flush()
        record_id = cost_record.id

    return record_id


def reserve_free_tier_vision_call(
    *,
    tenant_id: int,
    image_id: int,
    model: str,
    job_id: int | None = None,
) -> int:
    if model != "gemini-3.5-flash-lite":
        raise ValueError("Free-tier pricing is not configured for this model.")

    with SessionLocal.begin() as db:
        image = db.scalar(
            select(Image).where(
                Image.id == image_id,
                Image.tenant_id == tenant_id,
            )
        )
        if image is None:
            raise ValueError("Image not found for this tenant.")

        if job_id is not None:
            job = db.scalar(
                select(ProcessingJob).where(
                    ProcessingJob.id == job_id,
                    ProcessingJob.tenant_id == tenant_id,
                    ProcessingJob.job_type == "vision",
                )
            )
            if job is None:
                raise ValueError("Vision job not found for this tenant.")

        # Serialize budget reservations for this tenant.
        # PostgreSQL releases this lock when the transaction ends.
        db.execute(
            select(func.pg_advisory_xact_lock(784231, tenant_id))
        )

        recorded_calls, spent_usd = db.execute(
            select(
                func.count(AICallCost.id),
                func.coalesce(func.sum(AICallCost.cost_usd), 0.0),
            ).where(AICallCost.tenant_id == tenant_id)
        ).one()

        check_ai_limits(
            spent_usd=float(spent_usd),
            recorded_calls=recorded_calls,
            budget_usd=settings.ai_budget_usd,
            max_calls=settings.ai_max_calls,
            estimated_call_cost_usd=0.0,
        )

        record = AICallCost(
            tenant_id=tenant_id,
            provider="google",
            model=model,
            operation_type="vision",
            related_job_id=job_id,
            related_entity_type="image",
            related_entity_id=image_id,
            usage={
                "usage_available": False,
                "call_outcome": "reserved",
                "billing_tier": "free",
                "cost_basis": "free_tier_pricing",
            },
            cost_usd=0.0,
        )
        db.add(record)
        db.flush()
        record_id = record.id

    return record_id


def finish_free_tier_vision_call(
    *,
    tenant_id: int,
    record_id: int,
    usage: dict[str, object] | None,
) -> None:
    with SessionLocal.begin() as db:
        record = db.scalar(
            select(AICallCost)
            .where(
                AICallCost.id == record_id,
                AICallCost.tenant_id == tenant_id,
                AICallCost.provider == "google",
                AICallCost.model == "gemini-3.5-flash-lite",
                AICallCost.operation_type == "vision",
            )
            .with_for_update()
        )
        if record is None:
            raise ValueError("Vision call reservation not found.")

        if record.usage.get("call_outcome") != "reserved":
            raise ValueError("Vision call reservation already finalized.")

        record.usage = {
            **(usage or {}),
            "usage_available": bool(
                usage is not None and usage.get("usage_available", True)
            ),
            "call_outcome": (usage or {}).get(
                "call_outcome", "response_received"
            ),
            "billing_tier": "free",
            "cost_basis": "free_tier_pricing",
        }