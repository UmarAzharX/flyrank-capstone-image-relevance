from sqlalchemy import func, select

from app.budget import check_ai_limits
from app.config import settings
from app.database import SessionLocal
from app.embedding_vectors import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL
from app.models import AICallCost, Image, Post


def reserve_free_tier_embedding_call(
    *,
    tenant_id: int,
    owner_type: str,
    owner_id: int,
) -> int:
    if EMBEDDING_MODEL != "gemini-embedding-2":
        raise ValueError("Free-tier pricing is not configured for this model.")

    owner_model = {"image": Image, "post": Post}.get(owner_type)
    if owner_model is None:
        raise ValueError("Embedding owner must be an image or post.")

    with SessionLocal.begin() as db:
        owner = db.scalar(
            select(owner_model).where(
                owner_model.id == owner_id,
                owner_model.tenant_id == tenant_id,
            )
        )
        if owner is None:
            raise LookupError("Embedding owner not found for this tenant.")

        # Serialize embedding reservations with vision reservations.
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
            model=EMBEDDING_MODEL,
            operation_type="embedding",
            related_entity_type=owner_type,
            related_entity_id=owner_id,
            usage={
                "usage_available": False,
                "call_outcome": "reserved",
                "output_dimensionality": EMBEDDING_DIMENSIONS,
                "billing_tier": "free",
                "cost_basis": "free_tier_pricing",
            },
            cost_usd=0.0,
        )
        db.add(record)
        db.flush()
        record_id = record.id

    return record_id


def finish_free_tier_embedding_call(
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
                AICallCost.model == EMBEDDING_MODEL,
                AICallCost.operation_type == "embedding",
            )
            .with_for_update()
        )
        if record is None:
            raise LookupError("Embedding reservation not found.")

        if record.usage.get("call_outcome") != "reserved":
            raise ValueError("Embedding reservation already finalized.")

        record.usage = {
            **(usage or {}),
            "usage_available": bool(
                usage is not None and usage.get("usage_available", True)
            ),
            "call_outcome": (usage or {}).get(
                "call_outcome", "response_received"
            ),
            "output_dimensionality": record.usage["output_dimensionality"],
            "billing_tier": "free",
            "cost_basis": "free_tier_pricing",
        }
