import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Path as ApiPath, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Image, Post, Suggestion, Tenant
from app.schemas import (
    MatchingResponse,
    PostCreate,
    PostResponse,
    SuggestionResponse,
)
from app.suggestion_processing import generate_post_suggestions as process_post_suggestions


router = APIRouter(
    prefix="/posts",
    tags=["posts"],
)

DEMO_TENANT_NAME = "FlyRank Demo"
CORPUS_MANIFEST_PATH = Path(__file__).resolve().parents[2] / "data" / "images.json"


def get_demo_tenant(db: Session) -> Tenant:
    tenant = db.scalar(
        select(Tenant).where(Tenant.name == DEMO_TENANT_NAME)
    )
    if tenant is None:
        raise HTTPException(
            status_code=500,
            detail="Demo tenant not found",
        )
    return tenant


@router.get("", response_model=list[PostResponse])
def list_posts(db: Session = Depends(get_db)):
    tenant = get_demo_tenant(db)
    posts = db.scalars(
        select(Post)
        .where(Post.tenant_id == tenant.id)
        .order_by(Post.id)
    ).all()
    return posts


@router.get("/{post_id}", response_model=PostResponse)
def get_post(post_id: int, db: Session = Depends(get_db)):
    tenant = get_demo_tenant(db)
    post = db.scalar(
        select(Post).where(
            Post.id == post_id,
            Post.tenant_id == tenant.id,
        )
    )
    if post is None:
        raise HTTPException(
            status_code=404,
            detail="Post not found",
        )
    return post


@router.post("", response_model=PostResponse, status_code=201)
def create_post(
    payload: PostCreate,
    db: Session = Depends(get_db),
):
    tenant = get_demo_tenant(db)
    existing = db.scalar(
        select(Post).where(
            Post.tenant_id == tenant.id,
            Post.external_id == payload.external_id,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="Post external_id already exists for this tenant",
        )
    post = Post(
        tenant_id=tenant.id,
        external_id=payload.external_id,
        title=payload.title,
        content=payload.content,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


@router.post(
    "/{post_id}/suggestions",
    response_model=MatchingResponse,
)
def generate_post_suggestions(
    post_id: int = ApiPath(ge=1),
    top_k: int = Query(default=5, ge=1, le=50),
    db: Session = Depends(get_db),
) -> MatchingResponse:
    try:
        tenant = get_demo_tenant(db)
        post = db.scalar(
            select(Post).where(
                Post.id == post_id,
                Post.tenant_id == tenant.id,
            )
        )
        if post is None:
            raise HTTPException(
                status_code=404,
                detail="Post not found",
            )

        manifest_path = CORPUS_MANIFEST_PATH
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
        corpus_ids = {item["id"] for item in manifest}
        if len(corpus_ids) != len(manifest):
            raise ValueError("Duplicate corpus IDs found.")

        result = process_post_suggestions(
            tenant_id=tenant.id,
            external_id=post.external_id,
            corpus_ids=corpus_ids,
            limit=top_k,
        )

        saved_ids = result.saved_ids
        created_count = result.created_count

        rows = db.execute(
            select(
                Suggestion.id,
                Suggestion.image_id,
                Image.external_id.label("image_external_id"),
                Suggestion.similarity_score,
                Suggestion.guard_decision,
                Suggestion.explanation,
            )
            .join(Image, Image.id == Suggestion.image_id)
            .where(
                Suggestion.tenant_id == tenant.id,
                Suggestion.post_id == post.id,
                Image.tenant_id == tenant.id,
                Suggestion.id.in_(saved_ids),
            )
            .order_by(
                Suggestion.similarity_score.desc(),
                Image.external_id,
            )
        ).all()

        if len(rows) != len(saved_ids):
            raise LookupError("Saved suggestions were not found.")
        if any(row.guard_decision != "pass" for row in rows):
            raise ValueError("A saved suggestion failed the guard.")

        return MatchingResponse(
            post_id=post.id,
            created_count=created_count,
            reused_count=len(saved_ids) - created_count,
            match_status=result.match_status,
            candidates_checked=result.candidates_checked,
            no_match_reasons=result.no_match_reasons,
            suggestions=[
                SuggestionResponse(**dict(row._mapping))
                for row in rows
            ],
        )

    except HTTPException:
        raise
    except LookupError:
        raise HTTPException(
            status_code=409,
            detail="Post is not ready for matching. "
            "Check saved descriptions and embeddings.",
        ) from None
    except ValueError:
        raise HTTPException(
            status_code=409,
            detail="Matching data needs review.",
        ) from None
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Unable to generate suggestions.",
        ) from None
