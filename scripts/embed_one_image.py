import argparse
import math

from google.genai import errors
from sqlalchemy import select

from app.budget import AIUsageLimitError
from app.database import SessionLocal
from app.embedding_vectors import validate_and_normalize_vector
from app.image_embeddings import embed_image
from app.models import Embedding, Tenant


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate and persist one image embedding."
    )
    parser.add_argument("external_id", nargs="?", default="fox_001")
    args = parser.parse_args()

    try:
        with SessionLocal() as db:
            tenant_id = db.scalar(
                select(Tenant.id).where(Tenant.name == "FlyRank Demo")
            )
            if tenant_id is None:
                raise LookupError("Demo tenant not found.")

        embedding_id, created = embed_image(
            tenant_id=tenant_id,
            external_id=args.external_id,
        )

        with SessionLocal() as db:
            stored = db.scalar(
                select(Embedding).where(
                    Embedding.id == embedding_id,
                    Embedding.tenant_id == tenant_id,
                )
            )
            if stored is None:
                raise LookupError("Saved embedding not found.")

            validate_and_normalize_vector(stored.vector)
            vector_length = math.hypot(*stored.vector)
            if not math.isclose(vector_length, 1.0, abs_tol=1e-6):
                raise ValueError("Saved embedding is not normalized.")

            profile = stored.model_name
            dimensions = len(stored.vector)

    except AIUsageLimitError as exc:
        raise SystemExit(f"Embedding request blocked: {exc}") from None
    except errors.APIError as exc:
        raise SystemExit(
            f"Embedding request failed: HTTP {exc.code}."
        ) from None
    except Exception as exc:
        raise SystemExit(
            f"Embedding persistence failed: {type(exc).__name__}. "
            "Error details withheld to protect secrets."
        ) from None

    if created:
        print("Embedding saved and read back from PostgreSQL.")
    else:
        print("Embedding already exists. No Gemini request sent.")

    print("Embedding ID:", embedding_id)
    print("Configuration:", profile)
    print("Dimensions:", dimensions)
    print("Vector length:", f"{vector_length:.6f}")


if __name__ == "__main__":
    main()
