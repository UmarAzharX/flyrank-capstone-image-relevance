from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class VisionMetadata(BaseModel):
    subject: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=100)
    attributes: list[str]
    caption: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class ImageCreate(BaseModel):
    external_id: str
    filename: str
    source: str
    source_page_url: HttpUrl


class ImageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str
    filename: str
    source: str
    source_page_url: str
    processing_status: str
    created_at: datetime


class PostCreate(BaseModel):
    external_id: str
    title: str
    content: str


class PostResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str
    title: str
    content: str
    created_at: datetime


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_type: str
    status: str
    progress: int = Field(ge=0, le=100)
    retry_count: int = Field(ge=0)
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime


class JobCostSummary(BaseModel):
    job_id: int
    call_count: int = Field(ge=0)
    api_error_count: int = Field(ge=0)
    calls_with_usage: int = Field(ge=0)
    calls_without_usage: int = Field(ge=0)
    reported_total_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0)
    models: list[str]
