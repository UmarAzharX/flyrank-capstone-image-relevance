from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
    images: Mapped[list[Image]] = relationship(
        back_populates="tenant",
        cascade="all, delete-orphan",
    )
    posts: Mapped[list[Post]] = relationship(
        back_populates="tenant",
        cascade="all, delete-orphan",
    )


class Image(Base):
    __tablename__ = "images"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "external_id",
            name="uq_images_tenant_external_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    external_id: Mapped[str] = mapped_column(
        String(100),
        index=True,
        nullable=False,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_page_url: Mapped[str] = mapped_column(Text, nullable=False)
    processing_status: Mapped[str] = mapped_column(
        String(30),
        default="pending",
        index=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
    tenant: Mapped[Tenant] = relationship(back_populates="images")
    image_metadata: Mapped[ImageMetadata | None] = relationship(
        back_populates="image",
        cascade="all, delete-orphan",
        uselist=False,
    )


class ImageMetadata(Base):
    __tablename__ = "image_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    image_id: Mapped[int] = mapped_column(
        ForeignKey("images.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    subject: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    attributes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    caption: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    low_confidence: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
    image: Mapped[Image] = relationship(back_populates="image_metadata")


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "external_id",
            name="uq_posts_tenant_external_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    external_id: Mapped[str] = mapped_column(
        String(100),
        index=True,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
    tenant: Mapped[Tenant] = relationship(back_populates="posts")


class Embedding(Base):
    __tablename__ = "embeddings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "owner_type",
            "owner_id",
            "model_name",
            name="uq_embeddings_owner_model",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    owner_type: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    owner_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    vector: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )


class Suggestion(Base):
    __tablename__ = "suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    post_id: Mapped[int] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    image_id: Mapped[int] = mapped_column(
        ForeignKey("images.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    similarity_score: Mapped[float] = mapped_column(Float, nullable=False)
    guard_decision: Mapped[str] = mapped_column(String(30), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    suggestion_id: Mapped[int] = mapped_column(
        ForeignKey("suggestions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30),
        default="pending",
        index=True,
        nullable=False,
    )
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class AICallCost(Base):
    __tablename__ = "ai_call_costs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    related_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("processing_jobs.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    related_entity_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    related_entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usage: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
