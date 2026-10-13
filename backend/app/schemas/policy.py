from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PolicySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    policy_series_id: str
    version: int
    name: str
    filename: str
    file_type: str
    category: str
    carrier: str | None
    effective_date: date | None
    expires_date: date | None
    status: str
    ingestion_status: str
    chunk_count: int
    created_at: datetime

    @model_validator(mode="before")
    @classmethod
    def derive_current_policy_status(cls, value):
        if isinstance(value, dict):
            data = value.copy()
        else:
            data = {name: getattr(value, name, None) for name in cls.model_fields}
        if data.get("status") != "archived":
            today = date.today()
            expiry = data.get("expires_date")
            effective = data.get("effective_date")
            if expiry is not None and expiry < today:
                data["status"] = "expired"
            elif effective is not None and effective > today:
                data["status"] = "upcoming"
            else:
                data["status"] = "active"
        return data


class PolicyList(BaseModel):
    items: list[PolicySummary]
    total: int
    page: int
    page_size: int


class SearchFilters(BaseModel):
    category: str | None = None
    carrier: str | None = None
    policy_id: str | None = None
    status: Literal["active", "archived", "expired", "upcoming"] | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=10)
    filters: SearchFilters = Field(default_factory=SearchFilters)


class SearchResult(BaseModel):
    chunk_id: str
    document_id: str
    policy_name: str
    filename: str
    category: str
    carrier: str | None
    section: str
    page_number: int | None
    content: str
    similarity_score: float


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    total: int


class AnswerResponse(BaseModel):
    query: str
    answer: str
    abstained: bool
    sources: list[SearchResult]


class EvaluationRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    relevant_doc_ids: list[str] = Field(default_factory=list)
    config: dict[str, object] = Field(default_factory=dict)


class DashboardStats(BaseModel):
    policies: int
    indexed_policies: int
    processing_policies: int
    failed_policies: int
    chunks: int
    categories: list[dict[str, str | int]]
