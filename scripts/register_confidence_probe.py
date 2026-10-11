"""Register the downloaded confidence candidate without making an AI call."""

import argparse
import hashlib
import json
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Image, Tenant
from app.schemas import ImageCreate


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMAGE_ROOT = (PROJECT_ROOT / "data/images").resolve()
CANDIDATES = {
    "original": ("confidence_probe_001", "uncertain_002.jpg",
                 "confidence_probe_candidate_v1.json"),
    "fog": ("confidence_probe_fog_001", "uncertain_fog_001.jpg",
            "confidence_probe_fog_candidate_v1.json"),
}


def register_candidate(candidate):
    payload = ImageCreate(
        external_id=candidate["id"], filename=candidate["filename"],
        source=candidate["source"], source_page_url=candidate["source_page_url"],
    )
    if (payload.external_id, payload.filename) not in {
        (external_id, filename) for external_id, filename, _ in CANDIDATES.values()
    }:
        raise ValueError("Unexpected confidence candidate.")
    path = (IMAGE_ROOT / payload.filename).resolve()
    if not path.is_relative_to(IMAGE_ROOT) or not path.is_file():
        raise ValueError("Candidate must exist inside the image folder.")
    image_bytes = path.read_bytes()
    if not image_bytes.startswith(b"\xff\xd8\xff"):
        raise ValueError("Candidate is not a JPEG file.")
    if hashlib.sha256(image_bytes).hexdigest() != candidate["sha256"]:
        raise ValueError("Candidate image differs from its source record.")

    corpus = json.loads((PROJECT_ROOT / "data/images.json").read_text(encoding="utf-8-sig"))
    if any(item["id"] == payload.external_id or item["filename"] == payload.filename for item in corpus):
        raise ValueError("This candidate must stay outside the original evaluation corpus.")

    with SessionLocal.begin() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.name == "FlyRank Demo").with_for_update())
        if tenant is None:
            raise LookupError("Demo tenant not found.")
        existing = db.scalar(select(Image).where(
            Image.tenant_id == tenant.id, Image.external_id == payload.external_id,
        ))
        if existing is not None:
            if (existing.filename, existing.source, existing.source_page_url) != (
                payload.filename, payload.source, str(payload.source_page_url),
            ):
                raise ValueError("Existing candidate has different source details.")
            return existing.id, False
        image = Image(tenant_id=tenant.id, external_id=payload.external_id,
                      filename=payload.filename, source=payload.source,
                      source_page_url=str(payload.source_page_url), processing_status="pending")
        db.add(image)
        db.flush()
        return image.id, True


def main():
    parser = argparse.ArgumentParser(description="Register one separate confidence candidate.")
    parser.add_argument("--candidate", choices=CANDIDATES, default="original")
    args = parser.parse_args()
    expected_id, expected_filename, manifest_name = CANDIDATES[args.candidate]
    try:
        candidate = json.loads((PROJECT_ROOT / "data" / manifest_name).read_text(
            encoding="utf-8-sig",
        ))
        if (candidate["id"], candidate["filename"]) != (expected_id, expected_filename):
            raise ValueError("Candidate record does not match the selected test.")
        image_id, created = register_candidate(candidate)
    except Exception as exc:
        raise SystemExit(
            f"Candidate registration failed: {type(exc).__name__}. "
            "Error details withheld to protect secrets."
        ) from None
    print("Candidate registered." if created else "Candidate already registered; existing record reused.")
    print("Image ID:", image_id)
    print("External ID:", expected_id)
    print("File hash verified. No Gemini requests sent.")
    print("Original corpus and evaluation files were not changed.")


if __name__ == "__main__":
    main()
