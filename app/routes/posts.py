from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Post, Tenant
from app.schemas import PostCreate, PostResponse


router = APIRouter(
    prefix="/posts",
    tags=["posts"],
)

DEMO_TENANT_NAME = "FlyRank Demo"


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
