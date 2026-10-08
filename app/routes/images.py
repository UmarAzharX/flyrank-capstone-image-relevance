from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Image, Tenant
from app.schemas import ImageCreate, ImageResponse


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


router = APIRouter(
    prefix="/images",
    tags=["images"],
)


@router.get("", response_model=list[ImageResponse])
def list_images(db: Session = Depends(get_db)):
    images = db.scalars(select(Image).order_by(Image.id)).all()
    return images


@router.post("", response_model=ImageResponse, status_code=201)
def create_image(
    payload: ImageCreate,
    db: Session = Depends(get_db),
):
    tenant = get_demo_tenant(db)
    existing = db.scalar(
        select(Image).where(
            Image.tenant_id == tenant.id,
            Image.external_id == payload.external_id,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="Image external_id already exists for this tenant",
        )
    image = Image(
        tenant_id=tenant.id,
        external_id=payload.external_id,
        filename=payload.filename,
        source=payload.source,
        source_page_url=str(payload.source_page_url),
        processing_status="pending",
    )
    db.add(image)
    db.commit()
    db.refresh(image)
    return image


@router.get("/{image_id}", response_model=ImageResponse)
def get_image(image_id: int, db: Session = Depends(get_db)):
    image = db.get(Image, image_id)
    if image is None:
        raise HTTPException(
            status_code=404,
            detail="Image not found",
        )
    return image
