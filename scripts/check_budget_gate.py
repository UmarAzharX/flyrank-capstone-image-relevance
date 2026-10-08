from unittest.mock import patch

from sqlalchemy import func, select

from app.budget import AIUsageLimitError
from app.config import settings
from app.database import SessionLocal
from app.image_processing import process_image
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
            select(Image.tenant_id, Image.external_id)
            .join(Tenant)
            .where(
                Tenant.name == "FlyRank Demo",
                Image.processing_status == "pending",
                ~Image.image_metadata.has(),
            )
            .order_by(Image.id)
            .limit(1)
        ).first()

    if candidate is None:
        raise RuntimeError("No pending demo image available for this check.")

    tenant_id, external_id = candidate
    before = call_count(tenant_id)

    # Temporary setting change; .env remains unchanged.
    with (
        patch.object(settings, "ai_max_calls", 0),
        patch("app.image_processing.analyze_image") as gemini,
    ):
        try:
            process_image(
                tenant_id=tenant_id,
                external_id=external_id,
            )
        except AIUsageLimitError:
            pass
        else:
            raise AssertionError("The zero call cap did not block processing.")

        gemini.assert_not_called()

    if call_count(tenant_id) != before:
        raise AssertionError("Blocked processing created a cost record.")

    print("PASS: zero call cap blocked processing before Gemini.")
    print("PASS: no cost record was created.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit(
            f"Check failed: {type(exc).__name__}. "
            "Error details withheld to protect secrets."
        ) from None