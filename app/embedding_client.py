from google.genai import errors, types

from app.embedding_costs import (
    finish_free_tier_embedding_call,
    reserve_free_tier_embedding_call,
)
from app.embedding_vectors import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    validate_and_normalize_vector,
)
from app.gemini_client import create_gemini_client


def generate_text_embedding(
    *,
    tenant_id: int,
    owner_type: str,
    owner_id: int,
    text: str,
    title: str | None = None,
    job_id: int | None = None,
) -> list[float]:
    text = text.strip()
    if not text:
        raise ValueError("Embedding input must contain text.")

    if owner_type == "image":
        document_title = " ".join((title or "none").split()) or "none"
        contents = f"title: {document_title} | text: {text}"
    elif owner_type == "post":
        contents = f"task: search result | query: {text}"
    else:
        raise ValueError("Embedding owner must be an image or post.")

    record_id = reserve_free_tier_embedding_call(
        tenant_id=tenant_id,
        owner_type=owner_type,
        owner_id=owner_id,
        **({"job_id": job_id} if job_id is not None else {}),
    )
    print("Call slot reserved:", record_id)

    try:
        with create_gemini_client() as client:
            response = client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=contents,
                config=types.EmbedContentConfig(
                    output_dimensionality=EMBEDDING_DIMENSIONS,
                    http_options=types.HttpOptions(
                        timeout=60000,
                        retry_options=types.HttpRetryOptions(attempts=1),
                    ),
                ),
            )
    except Exception as exc:
        failure: dict[str, object] = {
            "usage_available": False,
            "call_outcome": "request_error",
            "error_type": type(exc).__name__,
        }
        if isinstance(exc, errors.APIError):
            failure["call_outcome"] = "api_error"
            failure["http_status"] = exc.code

        finish_free_tier_embedding_call(
            tenant_id=tenant_id,
            record_id=record_id,
            usage=failure,
        )
        raise

    embeddings = response.embeddings or []

    metadata = (
        response.metadata.model_dump(mode="json", exclude_none=True)
        if response.metadata is not None
        else {}
    )
    statistics = [
        embedding.statistics.model_dump(mode="json", exclude_none=True)
        for embedding in embeddings
        if embedding.statistics is not None
    ]

    usage = {
        "metadata": metadata,
        "embedding_statistics": statistics,
        "usage_available": (
            metadata.get("billable_character_count") is not None
            or any(
                item.get("token_count") is not None
                or bool(item.get("tokens_details"))
                for item in statistics
            )
        ),
    }

    finish_free_tier_embedding_call(
        tenant_id=tenant_id,
        record_id=record_id,
        usage=usage,
    )
    print("Cost record updated:", record_id)
    print("Reported usage:", usage)
    print("Cost USD: 0.00 (free tier)")

    if len(embeddings) != 1:
        raise ValueError("Expected exactly one embedding.")
    if embeddings[0].values is None:
        raise ValueError("Embedding values are missing.")
    if any(item.get("truncated") is True for item in statistics):
        raise ValueError("Embedding input was truncated.")

    return validate_and_normalize_vector(embeddings[0].values)
