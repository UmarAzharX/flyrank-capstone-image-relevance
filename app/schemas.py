from datetime import datetime
from typing import Literal
from pathlib import PureWindowsPath

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class VisionMetadata(BaseModel):
    subject: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=100)
    attributes: list[str]
    caption: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class ImageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1, max_length=100)
    filename: str = Field(min_length=1, max_length=255)
    source: str = Field(min_length=1, max_length=50)
    source_page_url: HttpUrl

    @field_validator("external_id", "filename", "source")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Text must not be blank.")
        return value

    @field_validator("filename")
    @classmethod
    def validate_image_filename(cls, value: str) -> str:
        # The worker reads one local JPG or PNG from data/images.
        forbidden = '<>:"/\\|?*'
        if any(char in forbidden or ord(char) < 32 for char in value):
            raise ValueError("Use a plain image filename without path characters.")
        if value.endswith((" ", ".")):
            raise ValueError("Filename must not end with a space or period.")
        reserved = {"CON", "PRN", "AUX", "NUL"} | {
            f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
        }
        if value.split(".", 1)[0].upper() in reserved:
            raise ValueError("Filename uses a reserved Windows name.")
        if PureWindowsPath(value).suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            raise ValueError("Use a JPG, JPEG, or PNG filename.")
        return value


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
    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=100000)

    @field_validator("external_id", "title", "content")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Text must not be blank.")
        return value


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


class SuggestionResponse(BaseModel):
    id: int
    image_id: int
    image_external_id: str
    similarity_score: float = Field(
        ge=-1.0, le=1.0, allow_inf_nan=False
    )
    guard_decision: str
    explanation: str


class MatchingResponse(BaseModel):
    post_id: int
    created_count: int = Field(ge=0)
    reused_count: int = Field(ge=0)
    suggestions: list[SuggestionResponse]
    match_status: Literal["matched", "no_confident_match"]
    candidates_checked: int = Field(ge=0)
    no_match_reasons: list[str]


class ReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accept", "reject"]
    review_note: str | None = Field(default=None, max_length=2000)


class ReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    suggestion_id: int
    decision: Literal["accept", "reject"]
    review_note: str | None
    created_at: datetime
