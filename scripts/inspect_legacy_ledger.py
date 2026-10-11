"""Inspect historical cost evidence without changing records or calling Gemini."""

import json
import math
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import engine
from app.models import AICallCost, Image, Tenant
from app.vision import VISION_MODEL

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KNOWN_OUTCOMES = {"reserved", "response_received", "api_error", "request_error"}


def safe_cost(row):
    usage = row.usage if isinstance(row.usage, dict) else {}
    outcome = usage.get("call_outcome")
    known = isinstance(outcome, str) and outcome in KNOWN_OUTCOMES
    available = usage.get("usage_available")
    return {
        "cost_id": row.id,
        "operation": row.operation_type if row.operation_type in {"vision", "embedding"} else "unknown",
        "owner_type": row.related_entity_type if row.related_entity_type in {"image", "post"} else "unknown",
        "owner_id": row.related_entity_id,
        "job_id": row.related_job_id,
        "created_at": row.created_at.isoformat(),
        "outcome": outcome if known else "unknown_or_legacy",
        "outcome_field_present": "call_outcome" in usage,
        "usage_available": available if type(available) is bool else None,
        "cost_usd": row.cost_usd if isinstance(row.cost_usd, (float, int)) and math.isfinite(row.cost_usd) else None,
    }


def inspect_ledger(db, corpus_ids):
    tenant_id = db.scalar(select(Tenant.id).where(Tenant.name == "FlyRank Demo"))
    if tenant_id is None:
        raise LookupError("Demo tenant not found.")
    images = db.scalars(select(Image).options(selectinload(Image.image_metadata)).where(
        Image.tenant_id == tenant_id, Image.external_id.in_(corpus_ids)
    )).all()
    if len(images) != len(corpus_ids):
        raise LookupError("Some corpus images are missing.")
    costs = db.scalars(select(AICallCost).where(
        AICallCost.tenant_id == tenant_id
    ).order_by(AICallCost.id)).all()
    unknown = []
    for row in costs:
        usage = row.usage if isinstance(row.usage, dict) else {}
        outcome = usage.get("call_outcome")
        if not isinstance(outcome, str) or outcome not in KNOWN_OUTCOMES:
            unknown.append(safe_cost(row))
    missing = []
    for image in sorted(images, key=lambda item: item.external_id):
        related = [row for row in costs if row.operation_type == "vision"
                   and row.related_entity_type == "image" and row.related_entity_id == image.id]
        confirmed = any(
            row.provider == "google" and row.model == VISION_MODEL
            and isinstance(row.usage, dict)
            and row.usage.get("call_outcome") == "response_received"
            for row in related
        )
        if not confirmed:
            metadata = image.image_metadata
            missing.append({
                "image_id": image.id, "external_id": image.external_id,
                "metadata_present": metadata is not None,
                "metadata_created_at": metadata.created_at.isoformat() if metadata else None,
                "related_vision_costs": [safe_cost(row) for row in related],
                "assessment": "Saved metadata does not establish the outcome of a particular historical call.",
            })
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tenant_id": tenant_id, "corpus_images_checked": len(images),
        "unknown_or_legacy_costs": unknown,
        "corpus_images_without_explicit_vision_response": missing,
        "database_writes": 0, "gemini_requests_sent": 0,
        "assessment": "Historical gaps remain unresolved unless independent contemporaneous evidence is available.",
        "limits": [
            "No missing outcomes were inferred from metadata, token usage, or timestamps.",
            "This diagnostic locates explicit response markers; it does not replace the full structural audit.",
            "Raw usage payloads and exception details are omitted.",
        ],
    }


def main():
    try:
        manifest = json.loads((PROJECT_ROOT / "data/images.json").read_text(encoding="utf-8-sig"))
        corpus_ids = {row["id"] for row in manifest}
        if not corpus_ids or len(corpus_ids) != len(manifest):
            raise ValueError("Invalid corpus manifest.")
        if engine.dialect.name != "postgresql":
            raise ValueError("Live inspection requires PostgreSQL.")
        with engine.connect().execution_options(
            isolation_level="REPEATABLE READ", postgresql_readonly=True
        ) as connection:
            with connection.begin():
                with Session(bind=connection, autoflush=False) as db:
                    report = inspect_ledger(db, corpus_ids)
        reports = PROJECT_ROOT / "reports"
        reports.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        output = reports / f"legacy_ledger_review_{stamp}.json"
        with output.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, allow_nan=False)
            handle.write("\n")
    except Exception as exc:
        raise SystemExit(f"Ledger inspection failed: {type(exc).__name__}. Error details withheld to protect secrets.") from None
    print("Unknown or legacy call outcomes:", len(report["unknown_or_legacy_costs"]))
    for row in report["unknown_or_legacy_costs"]:
        print(f"Cost {row['cost_id']} | operation={row['operation']} | "
              f"owner={row['owner_type']}:{row['owner_id']} | job={row['job_id']} | "
              f"outcome={row['outcome']} | usage_available={row['usage_available']}")
    missing = report["corpus_images_without_explicit_vision_response"]
    print("Corpus images without an explicit vision response:", len(missing))
    for row in missing:
        ids = [cost["cost_id"] for cost in row["related_vision_costs"]]
        print(f"{row['external_id']} | image_id={row['image_id']} | "
              f"metadata_present={row['metadata_present']} | related_vision_cost_ids={ids}")
    print("Existing metadata does not prove a particular historical call succeeded.")
    print("No records changed. No Gemini requests sent.")
    print("Report saved:", output)


if __name__ == "__main__":
    main()

