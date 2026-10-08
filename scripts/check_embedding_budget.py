from unittest.mock import patch

from sqlalchemy import func, select

from app.budget import AIUsageLimitError
from app.config import settings
from app.database import SessionLocal
from app.embedding_costs import reserve_free_tier_embedding_call
from app.models import AICallCost, Image, Tenant


def call_count(tenant_id: int) -> int:
    with SessionLocal() as db:
        return db.scalar(
            select(func.count(AICallCost.id)).where(
                AICallCost.tenant_id == tenant_id
            )
        )


def main() -> None:
    with SessionLocal() as db:
        candidate = db.execute(
            select(Image.tenant_id, Image.id)
            .join(Tenant)
            .where(
                Tenant.name == "FlyRank Demo",
                Image.external_id == "fox_001",
            )
        ).one_or_none()

    if candidate is None:
        raise LookupError("Demo fox image not found.")

    tenant_id, image_id = candidate
    before = call_count(tenant_id)

    with patch.object(settings, "ai_max_calls", 0):
        try:
            reserve_free_tier_embedding_call(
                tenant_id=tenant_id,
                owner_type="image",
                owner_id=image_id,
            )
        except AIUsageLimitError:
            pass
        else:
            raise AssertionError("The zero call cap did not block reservation.")

    if call_count(tenant_id) != before:
        raise AssertionError("Blocked reservation created a cost record.")

    print("PASS: zero call cap blocked embedding reservation.")
    print("PASS: no cost record was created.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit(
            f"Check failed: {type(exc).__name__}. "
            "Error details withheld to protect secrets."
        ) from None
