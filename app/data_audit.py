"""Inspect saved capstone data using SELECT queries only."""

import math
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.embedding_text import build_image_embedding_text, build_post_embedding_text
from app.embedding_vectors import EMBEDDING_MODEL, EMBEDDING_PROFILE, validate_and_normalize_vector
from app.models import AICallCost, Embedding, Image, Post, ProcessingJob, Tenant
from app.schemas import VisionMetadata


def audit_saved_data(db, *, image_sources, post_sources, confidence_threshold,
                     vision_model, max_calls, budget_usd):
    """Return counts and safe issue codes, without writing or making AI calls.

    Audit one tenant. Non-corpus owners (for example the scientific-name probe)
    are checked for ownership but excluded from corpus completion counts.
    """
    image_ids = [item["id"] for item in image_sources]
    post_ids = [item["id"] for item in post_sources]
    for ids in (image_ids, post_ids):
        if not ids or any(type(value) is not str or not value.strip() for value in ids) or len(set(ids)) != len(ids):
            raise ValueError("Audit source IDs must be nonempty and unique.")

    errors, warnings = [], []

    def issue(target, code, kind, record_id=None):
        item = {"code": code, "record_type": kind}
        if record_id is not None:
            item["record_id"] = record_id
        target.append(item)

    with db.no_autoflush:
        tenant = db.scalar(select(Tenant).where(Tenant.name == "FlyRank Demo"))
        if tenant is None:
            raise LookupError("Demo tenant not found.")
        tenant_id = tenant.id
        images = db.scalars(select(Image).options(selectinload(Image.image_metadata)).where(
            Image.tenant_id == tenant_id,
        )).all()
        posts = db.scalars(select(Post).where(Post.tenant_id == tenant_id)).all()
        vectors = db.scalars(select(Embedding).where(Embedding.tenant_id == tenant_id)).all()
        jobs = db.scalars(select(ProcessingJob).where(ProcessingJob.tenant_id == tenant_id)).all()
        ledger = db.scalars(select(AICallCost).where(AICallCost.tenant_id == tenant_id)).all()

    image_by_external = {row.external_id: row for row in images}
    post_by_external = {row.external_id: row for row in posts}
    owners = {"image": {row.id for row in images}, "post": {row.id for row in posts}}
    scoped_images, scoped_posts = set(), set()
    valid_metadata, valid_posts, low_count = 0, 0, 0
    confidences = []
    for source in image_sources:
        image = image_by_external.get(source["id"])
        if image is None:
            issue(errors, "corpus_image_missing", "image")
            continue
        scoped_images.add(image.id)
        if image.filename != source["filename"]:
            issue(errors, "manifest_filename_differs", "image", image.id)
        metadata = image.image_metadata
        if metadata is None:
            issue(errors, "vision_metadata_missing", "image", image.id)
            continue
        try:
            validated = VisionMetadata.model_validate({
                "subject": metadata.subject, "category": metadata.category,
                "attributes": metadata.attributes, "caption": metadata.caption,
                "confidence": metadata.confidence,
            })
            build_image_embedding_text(validated)
        except (ValueError, TypeError):
            issue(errors, "vision_metadata_invalid", "image", image.id)
            continue
        valid_metadata += 1
        confidences.append(validated.confidence)
        low = validated.confidence < confidence_threshold
        low_count += int(low)
        if metadata.low_confidence is not low:
            issue(errors, "low_confidence_flag_differs", "image", image.id)
        if image.processing_status != ("needs_review" if low else "tagged"):
            issue(errors, "image_processing_status_differs", "image", image.id)

    for source in post_sources:
        post = post_by_external.get(source["id"])
        if post is None:
            issue(errors, "evaluation_post_missing", "post")
            continue
        scoped_posts.add(post.id)
        if (post.title, post.content) != (source["title"], source["content"]):
            issue(errors, "evaluation_post_text_differs", "post", post.id)
            continue
        try:
            build_post_embedding_text(title=post.title, content=post.content)
        except (ValueError, TypeError):
            issue(errors, "evaluation_post_text_invalid", "post", post.id)
            continue
        valid_posts += 1

    seen, valid_vectors = set(), set()
    inactive_profiles = 0
    for row in vectors:
        if row.owner_type not in owners or row.owner_id not in owners[row.owner_type]:
            issue(errors, "embedding_owner_not_in_tenant", "embedding", row.id)
            continue
        key = (row.owner_type, row.owner_id, row.model_name)
        if key in seen:
            issue(errors, "embedding_owner_profile_duplicate", "embedding", row.id)
        seen.add(key)
        if row.model_name != EMBEDDING_PROFILE:
            inactive_profiles += 1
            continue
        try:
            validate_and_normalize_vector(row.vector)
            # Validation returns a new normalized list; never assign it to the row.
            if not math.isclose(math.hypot(*row.vector), 1.0, rel_tol=1e-6, abs_tol=1e-6):
                raise ValueError("Saved vector is not normalized.")
        except (ValueError, TypeError):
            issue(errors, "embedding_vector_invalid", "embedding", row.id)
            continue
        valid_vectors.add((row.owner_type, row.owner_id))

    image_vectors = sum(("image", value) in valid_vectors for value in scoped_images)
    post_vectors = sum(("post", value) in valid_vectors for value in scoped_posts)
    if image_vectors != len(image_ids):
        issue(errors, "corpus_embeddings_incomplete", "embedding")
    if post_vectors != len(post_ids):
        issue(errors, "evaluation_embeddings_incomplete", "embedding")

    jobs_by_id = {row.id: row for row in jobs}
    job_summary = []
    for row in sorted(jobs, key=lambda item: item.id):
        known_state = row.status in {"pending", "queued", "queued_batch", "running", "completed", "failed"}
        known_type = row.job_type in {"vision", "embedding"}
        if not known_state or not known_type:
            issue(errors, "job_type_or_status_unknown", "job", row.id)
        if not 0 <= row.progress <= 100 or row.retry_count < 0:
            issue(errors, "job_progress_or_retry_count_invalid", "job", row.id)
        if row.status == "completed" and row.progress != 100:
            issue(errors, "completed_job_progress_not_100", "job", row.id)
        if row.status in {"queued", "queued_batch", "running"}:
            issue(warnings, "job_in_progress", "job", row.id)
        job_summary.append({"id": row.id, "job_type": row.job_type if known_type else "unknown",
                            "status": row.status if known_state else "unknown", "progress": row.progress,
                            "retry_count": row.retry_count,
                            "has_failure_reason": row.failure_reason is not None})

    outcomes = Counter()
    response_owners = set()
    total_cost, with_usage, linked_calls = 0.0, 0, 0
    structurally_valid = 0
    for row in ledger:
        previous_errors = len(errors)
        expected_model = {"vision": vision_model, "embedding": EMBEDDING_MODEL}.get(row.operation_type)
        if expected_model is None or row.provider != "google" or row.model != expected_model:
            issue(errors, "ledger_provider_model_or_operation_invalid", "cost", row.id)
        valid_owner = row.related_entity_type in owners and row.related_entity_id in owners[row.related_entity_type]
        if not valid_owner or (row.operation_type == "vision" and row.related_entity_type != "image"):
            issue(errors, "ledger_owner_not_in_tenant", "cost", row.id)
        if row.related_job_id is not None:
            linked_calls += 1
            job = jobs_by_id.get(row.related_job_id)
            if job is None or job.job_type != row.operation_type:
                issue(errors, "ledger_job_not_in_tenant_or_wrong_type", "cost", row.id)
        if type(row.cost_usd) not in (int, float) or not math.isfinite(row.cost_usd) or row.cost_usd < 0:
            issue(errors, "ledger_cost_invalid", "cost", row.id)
        else:
            total_cost += row.cost_usd
        if not isinstance(row.usage, dict):
            issue(errors, "ledger_usage_invalid", "cost", row.id)
        else:
            available = row.usage.get("usage_available")
            if type(available) is not bool:
                issue(warnings, "ledger_usage_availability_missing", "cost", row.id)
            with_usage += int(available is True)
            outcome = row.usage.get("call_outcome")
            known = outcome in {"reserved", "response_received", "api_error", "request_error"} if isinstance(outcome, str) else False
            outcomes[outcome if known else "unknown"] += 1
            if not known:
                issue(warnings, "ledger_outcome_unknown_or_legacy", "cost", row.id)
            elif outcome == "reserved":
                issue(warnings, "ledger_reservation_unfinished", "cost", row.id)
            if row.usage.get("billing_tier") != "free":
                issue(warnings, "ledger_free_tier_marker_missing", "cost", row.id)
            elif row.cost_usd != 0:
                issue(errors, "free_tier_cost_not_zero", "cost", row.id)
            if outcome == "response_received" and valid_owner and expected_model and len(errors) == previous_errors:
                response_owners.add((row.operation_type, row.related_entity_type, row.related_entity_id))
        structurally_valid += int(len(errors) == previous_errors)

    missing_vision = sum(("vision", "image", value) not in response_owners for value in scoped_images)
    missing_embeddings = sum(("embedding", owner_type, owner_id) not in response_owners
                             for owner_type, ids in (("image", scoped_images), ("post", scoped_posts))
                             for owner_id in ids)
    if missing_vision:
        issue(warnings, "corpus_owner_without_vision_response_record", "cost")
    if missing_embeddings:
        issue(warnings, "scoped_owner_without_embedding_response_record", "cost")
    if len(ledger) >= max_calls:
        issue(warnings, "configured_call_limit_reached", "cost")
    if total_cost > budget_usd:
        issue(warnings, "recorded_cost_above_configured_budget", "cost")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "FlyRank Demo: corpus metadata, evaluation posts, and tenant-owned vectors/jobs/costs",
        "read_only": True, "gemini_requests_sent": 0, "tenant_id": tenant_id,
        "embedding_profile": EMBEDDING_PROFILE, "confidence_threshold": confidence_threshold,
        "images": {"expected": len(image_ids), "present": len(scoped_images),
                   "schema_valid_metadata": valid_metadata, "low_confidence_count": low_count,
                   "minimum_confidence": min(confidences, default=None),
                   "maximum_confidence": max(confidences, default=None)},
        "posts": {"expected": len(post_ids), "present": len(scoped_posts), "source_text_matches": valid_posts},
        "embeddings": {"valid_corpus_images": image_vectors, "valid_evaluation_posts": post_vectors,
                       "other_valid_current_profile": len(valid_vectors) - image_vectors - post_vectors,
                       "inactive_profile_count": inactive_profiles},
        "costs": {"record_count": len(ledger), "structurally_valid_records": structurally_valid,
                  "cost_usd": total_cost, "calls_with_usage": with_usage,
                  "calls_without_reported_usage": len(ledger) - with_usage,
                  "job_linked_records": linked_calls, "standalone_records": len(ledger) - linked_calls,
                  "outcomes": dict(sorted(outcomes.items())),
                  "corpus_owners_without_vision_response_record": missing_vision,
                  "scoped_owners_without_embedding_response_record": missing_embeddings},
        "jobs": job_summary, "errors": errors, "warnings": warnings,
        "status": "fail" if errors else ("review" if warnings else "pass"),
        "live_low_confidence_example_present": low_count > 0,
        "limits": [
            "Response records are owner-level evidence; they do not identify the exact call that produced each artifact.",
            "Unrecorded historical calls cannot be discovered from this ledger alone.",
            "No input hashes exist to prove cached vectors match unchanged image descriptions.",
            "Missing usage is not measured zero usage; USD 0 assumes the declared free tier.",
        ],
    }
