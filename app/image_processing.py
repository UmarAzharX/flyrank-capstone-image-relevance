from pathlib import Path

from google.genai import errors
from sqlalchemy import select

from app.config import settings
from app.cost_tracking import (
    finish_free_tier_vision_call,
    reserve_free_tier_vision_call,
)
from app.database import SessionLocal
from app.models import Image, ImageMetadata, ProcessingJob
from app.vision import VISION_MODEL, analyze_image

IMAGE_ROOT = (
    Path(__file__).resolve().parents[1] / "data" / "images"
).resolve()


def process_image(
    *,
    tenant_id: int,
    external_id: str,
    job_id: int | None = None,
) -> int | None:
    with SessionLocal.begin() as db:
        image = db.scalar(
            select(Image)
            .where(
                Image.tenant_id == tenant_id,
                Image.external_id == external_id,
            )
            .with_for_update()
        )
        if image is None:
            raise LookupError("Image not found for this tenant.")

        if job_id is not None:
            job = db.scalar(
                select(ProcessingJob).where(
                    ProcessingJob.id == job_id,
                    ProcessingJob.tenant_id == tenant_id,
                    ProcessingJob.job_type == "vision",
                    ProcessingJob.status == "running",
                )
            )
            if job is None:
                raise LookupError("Running vision job not found for this tenant.")

        if image.image_metadata is not None:
            return None

        image_path = (IMAGE_ROOT / image.filename).resolve()
        if not image_path.is_relative_to(IMAGE_ROOT):
            raise ValueError("Image path must stay inside the image folder.")
        if not image_path.is_file():
            raise ValueError("Local image file not found.")
        if image_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            raise ValueError("Unsupported image format.")

        record_id = reserve_free_tier_vision_call(
            tenant_id=tenant_id,
            image_id=image.id,
            model=VISION_MODEL,
            job_id=job_id,
        )
        print("Call slot reserved:", record_id)

        def save_usage(
            model: str,
            usage: dict[str, object] | None,
        ) -> None:
            if model != VISION_MODEL:
                raise ValueError("Response model does not match reservation.")

            finish_free_tier_vision_call(
                tenant_id=tenant_id,
                record_id=record_id,
                usage=usage,
            )
            print("Cost record updated:", record_id)
            print("Cost USD: 0.00 (free tier)")

        try:
            metadata = analyze_image(image_path, on_usage=save_usage)
        except errors.APIError as exc:
            save_usage(
                VISION_MODEL,
                {
                    "usage_available": False,
                    "call_outcome": "api_error",
                    "http_status": exc.code,
                },
            )
            raise
        low_confidence = (
            metadata.confidence < settings.vision_confidence_threshold
        )

        db.add(
            ImageMetadata(
                image_id=image.id,
                subject=metadata.subject,
                category=metadata.category,
                attributes=metadata.attributes,
                caption=metadata.caption,
                confidence=metadata.confidence,
                low_confidence=low_confidence,
            )
        )
        image.processing_status = (
            "needs_review" if low_confidence else "tagged"
        )
        image_id = image.id

    return image_id