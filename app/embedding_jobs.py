import json
import math
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.database import SessionLocal
from app.embedding_text import build_image_embedding_text, build_post_embedding_text
from app.embedding_vectors import EMBEDDING_PROFILE, validate_and_normalize_vector
from app.models import Embedding, Image, Post, ProcessingJob, Tenant
from app.schemas import PostCreate, VisionMetadata


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EMBEDDING_JOB_TYPE = "embedding"


@dataclass(frozen=True)
class EmbeddingWorkItem:
    owner_type: str
    owner_id: int
    external_id: str


@dataclass(frozen=True)
class EmbeddingSnapshot:
    image_completed: int
    image_total: int
    post_completed: int
    post_total: int
    pending: list[EmbeddingWorkItem]

    @property
    def progress(self):
        total = self.image_total + self.post_total
        return (self.image_completed + self.post_completed) * 100 // total


@dataclass(frozen=True)
class EmbeddingJobResult:
    job_id: int
    status: str
    progress: int
    created: bool
    snapshot: EmbeddingSnapshot


def load_embedding_scope(root: Path = PROJECT_ROOT):
    images = json.loads((root / "data" / "images.json").read_text(encoding="utf-8"))
    posts = json.loads((root / "data" / "eval_posts.json").read_text(encoding="utf-8"))
    image_ids = [item["id"] for item in images]
    post_ids = [item["id"] for item in posts]
    for ids in (image_ids, post_ids):
        if not ids or any(type(value) is not str or not value.strip() for value in ids) or len(ids) != len(set(ids)):
            raise ValueError("Embedding manifests must have nonempty unique IDs.")
    payloads = [PostCreate(external_id=item["id"], title=item["title"], content=item["content"]) for item in posts]
    return set(image_ids), payloads


def embedding_snapshot(db: Session, *, tenant_id: int, image_ids: set[str],
                       post_sources: list[PostCreate]) -> EmbeddingSnapshot:
    post_ids = [source.external_id for source in post_sources]
    if not image_ids or not post_ids or len(set(post_ids)) != len(post_ids):
        raise ValueError("Embedding scope must be nonempty with unique post IDs.")
    images = db.scalars(select(Image).options(selectinload(Image.image_metadata)).where(
        Image.tenant_id == tenant_id, Image.external_id.in_(image_ids)
    ).order_by(Image.id)).all()
    posts = db.scalars(select(Post).where(
        Post.tenant_id == tenant_id, Post.external_id.in_(post_ids)
    ).order_by(Post.id)).all()
    if len(images) != len(image_ids) or len(posts) != len(post_ids):
        raise LookupError("All scoped images and posts must be seeded for this tenant.")
    for image in images:
        metadata = image.image_metadata
        if metadata is None:
            raise LookupError("Complete vision metadata before creating an embedding job.")
        build_image_embedding_text(VisionMetadata(
            subject=metadata.subject, category=metadata.category, attributes=metadata.attributes,
            caption=metadata.caption, confidence=metadata.confidence,
        ))
    by_external_id = {post.external_id: post for post in posts}
    for source in post_sources:
        post = by_external_id[source.external_id]
        if post.title != source.title or post.content != source.content:
            raise ValueError("Saved post text differs from the embedding source.")
        build_post_embedding_text(title=post.title, content=post.content)

    embeddings = db.scalars(select(Embedding).where(
        Embedding.tenant_id == tenant_id, Embedding.model_name == EMBEDDING_PROFILE,
        or_(
            (Embedding.owner_type == "image") & Embedding.owner_id.in_([image.id for image in images]),
            (Embedding.owner_type == "post") & Embedding.owner_id.in_([post.id for post in posts]),
        ),
    )).all()
    completed = set()
    for embedding in embeddings:
        validate_and_normalize_vector(embedding.vector)
        if not math.isclose(math.hypot(*embedding.vector), 1.0, rel_tol=1e-6, abs_tol=1e-6):
            raise ValueError("Saved embedding is not normalized.")
        key = (embedding.owner_type, embedding.owner_id)
        if key in completed:
            raise ValueError("Duplicate scoped embedding.")
        completed.add(key)
    pending = [EmbeddingWorkItem(owner_type, owner.id, owner.external_id)
               for owner_type, owners in (("image", images), ("post", posts))
               for owner in owners if (owner_type, owner.id) not in completed]
    return EmbeddingSnapshot(
        image_completed=sum(("image", image.id) in completed for image in images),
        image_total=len(images),
        post_completed=sum(("post", post.id) in completed for post in posts),
        post_total=len(posts), pending=pending,
    )


def create_or_get_embedding_job(*, tenant_id: int, image_ids: set[str],
                                post_sources: list[PostCreate]) -> EmbeddingJobResult:
    with SessionLocal.begin() as db:
        # Serializes job creation for this tenant on PostgreSQL.
        tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
        if tenant is None:
            raise LookupError("Tenant not found.")
        snapshot = embedding_snapshot(db, tenant_id=tenant_id, image_ids=image_ids,
                                      post_sources=post_sources)
        job = db.scalar(select(ProcessingJob).where(
            ProcessingJob.tenant_id == tenant_id, ProcessingJob.job_type == EMBEDDING_JOB_TYPE,
            ProcessingJob.status.in_(["pending", "queued_batch", "running"]),
        ).order_by(ProcessingJob.id).limit(1).with_for_update())
        if job is None and not snapshot.pending:
            job = db.scalar(select(ProcessingJob).where(
                ProcessingJob.tenant_id == tenant_id, ProcessingJob.job_type == EMBEDDING_JOB_TYPE,
                ProcessingJob.status == "completed",
            ).order_by(ProcessingJob.id.desc()).limit(1).with_for_update())
        created = job is None
        if created:
            job = ProcessingJob(tenant_id=tenant_id, job_type=EMBEDDING_JOB_TYPE,
                                status="pending", progress=snapshot.progress, retry_count=0)
            db.add(job)
        elif job.status == "pending":
            job.progress = snapshot.progress
        db.flush()
        return EmbeddingJobResult(job.id, job.status, job.progress, created, snapshot)
