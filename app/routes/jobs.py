from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path as ApiPath, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.embedding_worker import run_queued_embedding_batch
from app.models import AICallCost, ProcessingJob, Tenant
from app.routes.images import get_demo_tenant
from app.schemas import JobCostSummary, JobResponse
from app.vision_batch import run_queued_vision_batch
from app.vision_worker import run_queued_vision_job

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: int, db: Session = Depends(get_db)):
    tenant = get_demo_tenant(db)

    job = db.scalar(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.tenant_id == tenant.id,
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return job


@router.post(
    "/{job_id}/run-one",
    response_model=JobResponse,
    status_code=202,
)
def start_one_worker_step(
    job_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    tenant = get_demo_tenant(db)

    job = db.scalar(
        select(ProcessingJob)
        .where(
            ProcessingJob.id == job_id,
            ProcessingJob.tenant_id == tenant.id,
            ProcessingJob.job_type == "vision",
        )
        .with_for_update()
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != "pending":
        raise HTTPException(
            status_code=409,
            detail="Job must be pending before it can be queued",
        )

    job.status = "queued"
    job.failure_reason = None
    db.commit()
    db.refresh(job)

    response = JobResponse.model_validate(job)
    background_tasks.add_task(run_queued_vision_job, job_id)
    return response


@router.get("/{job_id}/costs", response_model=JobCostSummary)
def get_job_costs(job_id: int, db: Session = Depends(get_db)):
    job = get_job(job_id, db)

    records = db.scalars(
        select(AICallCost).where(
            AICallCost.tenant_id == job.tenant_id,
            AICallCost.related_job_id == job.id,
        )
    ).all()

    calls_with_usage = sum(
        record.usage.get("usage_available") is True
        for record in records
    )

    reported_total_tokens = 0
    for record in records:
        tokens = record.usage.get("total_token_count")
        if type(tokens) is int and tokens >= 0:
            reported_total_tokens += tokens

    return JobCostSummary(
        job_id=job.id,
        call_count=len(records),
        api_error_count=sum(
            record.usage.get("call_outcome") == "api_error"
            for record in records
        ),
        calls_with_usage=calls_with_usage,
        calls_without_usage=len(records) - calls_with_usage,
        reported_total_tokens=reported_total_tokens,
        cost_usd=sum((record.cost_usd for record in records), 0.0),
        models=sorted({record.model for record in records}),
    )


@router.post(
    "/{job_id}/run-batch",
    response_model=JobResponse,
    status_code=202,
)
def start_batch(
    job_id: int,
    background_tasks: BackgroundTasks,
    max_steps: int = Query(default=2, ge=1, le=50),
    pause_seconds: int = Query(default=15, ge=0, le=60),
    db: Session = Depends(get_db),
):
    tenant = get_demo_tenant(db)

    job = db.scalar(
        select(ProcessingJob)
        .where(
            ProcessingJob.id == job_id,
            ProcessingJob.tenant_id == tenant.id,
            ProcessingJob.job_type == "vision",
        )
        .with_for_update()
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Vision job not found")

    if job.status != "pending":
        raise HTTPException(
            status_code=409,
            detail="Job must be pending before a batch can be queued",
        )

    job.status = "queued_batch"
    job.failure_reason = None
    db.flush()

    response = JobResponse.model_validate(job)
    db.commit()

    background_tasks.add_task(
        run_queued_vision_batch,
        job_id,
        max_steps=max_steps,
        pause_seconds=pause_seconds,
    )
    return response


@router.post("/{job_id}/resume", response_model=JobResponse)
def resume_job(
    job_id: int,
    db: Session = Depends(get_db),
):
    tenant = get_demo_tenant(db)

    # Serialize job creation/resumption for this tenant.
    db.execute(
        select(Tenant.id)
        .where(Tenant.id == tenant.id)
        .with_for_update()
    )

    job = db.scalar(
        select(ProcessingJob)
        .where(
            ProcessingJob.id == job_id,
            ProcessingJob.tenant_id == tenant.id,
            ProcessingJob.job_type.in_(["vision", "embedding"]),
        )
        .with_for_update()
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != "failed":
        raise HTTPException(
            status_code=409,
            detail="Only a failed job can be resumed",
        )

    other_active_job = db.scalar(
        select(ProcessingJob.id)
        .where(
            ProcessingJob.tenant_id == tenant.id,
            ProcessingJob.job_type == job.job_type,
            ProcessingJob.id != job.id,
            ProcessingJob.status.in_(
                ["pending", "queued", "queued_batch", "running"]
            ),
        )
        .limit(1)
    )
    if other_active_job is not None:
        raise HTTPException(
            status_code=409,
            detail="Another job of this type is active",
        )

    job.status = "pending"
    job.failure_reason = None
    db.flush()

    response = JobResponse.model_validate(job)
    db.commit()
    return response


@router.post("/{job_id}/run-embeddings", response_model=JobResponse, status_code=202)
def start_embedding_batch(
    background_tasks: BackgroundTasks,
    job_id: int = ApiPath(ge=1),
    max_steps: int = Query(default=3, ge=1, le=60),
    pause_seconds: int = Query(default=15, ge=0, le=60),
    db: Session = Depends(get_db),
):
    tenant = get_demo_tenant(db)
    job = db.scalar(select(ProcessingJob).where(
        ProcessingJob.id == job_id, ProcessingJob.tenant_id == tenant.id,
        ProcessingJob.job_type == "embedding",
    ).with_for_update())
    if job is None:
        raise HTTPException(status_code=404, detail="Embedding job not found")
    if job.status != "pending":
        raise HTTPException(status_code=409, detail="Embedding job must be pending before it can be queued")
    job.status = "queued_batch"
    job.failure_reason = None
    db.flush()
    response = JobResponse.model_validate(job)
    db.commit()
    background_tasks.add_task(run_queued_embedding_batch, job_id,
                              max_steps=max_steps, pause_seconds=pause_seconds)
    return response
