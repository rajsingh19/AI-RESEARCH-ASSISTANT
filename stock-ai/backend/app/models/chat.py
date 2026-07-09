from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator


class IntentType(str, Enum):
    COMPANY_METRIC = "company_metric"
    COMPANY_OVERVIEW = "company_overview"
    COMPARE_COMPANIES = "compare_companies"
    RANKING = "ranking"
    UNKNOWN = "unknown"


class MetricName(str, Enum):
    REVENUE = "revenue"
    PROFIT = "profit"
    EPS = "eps"
    PE_RATIO = "pe_ratio"


class ChatRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        examples=[
            "What is TCS revenue?",
            "Compare Infosys and TCS.",
            "Which company has higher profit?",
            "Latest news on TCS",
        ],
    )
    session_id: str | None = Field(
        default="default_session",
        description="Optional session ID for conversation memory tracking."
    )

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Question cannot be empty.")
        return cleaned


class ExtractedQuery(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    intent: IntentType = Field(
        default=IntentType.UNKNOWN,
        description="The user's core request type.",
    )
    company_identifiers: list[str] = Field(
        default_factory=list,
        description="Ticker symbols chosen from the supported company catalog.",
    )
    metrics: list[MetricName] = Field(
        default_factory=list,
        description="Requested financial metrics.",
    )
    requires_all_companies: bool = Field(
        default=False,
        description="True when the request needs a full-table comparison.",
    )


class CompanySnapshot(BaseModel):
    ticker: str
    company_name: str
    revenue: float
    profit: float
    eps: float
    pe_ratio: float
    last_updated: str | None = None
    data_source: str | None = None
    is_live: bool | None = None
    reporting_period: str | None = None


class RetrievalContext(BaseModel):
    companies: list[CompanySnapshot] = Field(default_factory=list)
    requested_metrics: list[MetricName] = Field(default_factory=list)
    unavailable_identifiers: list[str] = Field(default_factory=list)
    analysis_notes: list[str] = Field(default_factory=list)
    company_metadata: dict[str, dict[str, Any]] = Field(default_factory=dict)
    company_history: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    company_dividends: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)


# ── Phase 7 models ─────────────────────────────────────────────────────────────

class DocumentChunk(BaseModel):
    """A single retrieved chunk from ChromaDB (annual reports / filings)."""

    chunk_id: str = Field(description="Unique ID, e.g. TCS_Q4.pdf::3")
    document: str = Field(description="Source filename, e.g. TCS_Q4.pdf")
    content: str = Field(description="Raw text of the chunk")
    relevance_score: float | None = Field(
        default=None,
        description="Cosine distance from ChromaDB (lower = more relevant)",
    )


class HybridChatResponse(BaseModel):
    """Phase 7 response — answer + structured SQL data + document citations."""

    model_config = ConfigDict(use_enum_values=True)

    answer: str = Field(..., min_length=1)
    intent: IntentType
    companies: list[str] = Field(default_factory=list)
    metrics: list[MetricName] = Field(default_factory=list)
    structured_data: dict[str, Any] = Field(default_factory=dict)
    retrieved_documents: list[DocumentChunk] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ── Phase 8 models ─────────────────────────────────────────────────────────────

class NewsArticle(BaseModel):
    """
    A single news article fetched from a news provider (NewsAPI, Finnhub, etc.).
    This is the raw fetch result before chunking and embedding.
    """

    article_id: str = Field(description="SHA256 hash of URL — dedup key")
    title: str
    content: str = Field(description="Full article body text")
    source: str = Field(description="Publisher name, e.g. 'Economic Times'")
    author: str | None = None
    published_at: datetime
    url: str
    company: str = Field(description="Ticker this article was fetched for")


class NewsChunk(BaseModel):
    """
    A single retrieved chunk from the news ChromaDB collection.
    Carries full citation metadata for the response.
    """

    chunk_id: str = Field(description="e.g. 'abc123::0'")
    article_id: str
    title: str
    source: str
    author: str | None = None
    published_at: str = Field(description="ISO 8601 string")
    url: str
    company: str
    content: str
    relevance_score: float | None = None


class NewsResponse(BaseModel):
    """
    Phase 8 response — answer + financial data + document chunks + live news.
    This is the richest response format in the system.
    """

    model_config = ConfigDict(use_enum_values=True)

    answer: str = Field(..., min_length=1)
    intent: IntentType
    companies: list[str] = Field(default_factory=list)
    metrics: list[MetricName] = Field(default_factory=list)

    # From SQLite
    financial_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured financial metrics per ticker from SQLite.",
    )

    # From ChromaDB — annual reports / filings
    documents: list[DocumentChunk] = Field(
        default_factory=list,
        description="Retrieved document chunks from annual reports and filings.",
    )

    # From ChromaDB — live news collection
    news: list[NewsChunk] = Field(
        default_factory=list,
        description="Retrieved news chunks with full citation metadata.",
    )

    # Human-readable source list
    sources: list[str] = Field(
        default_factory=list,
        description="e.g. ['SQLite', 'TCS_Annual_Report.pdf', 'Economic Times']",
    )

    warnings: list[str] = Field(default_factory=list)


# ── Phase 6 backward-compat ────────────────────────────────────────────────────

class ChatResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    answer: str = Field(..., min_length=1)
    intent: IntentType
    companies: list[str] = Field(default_factory=list)
    metrics: list[MetricName] = Field(default_factory=list)
    source: Literal["sqlite", "hybrid"] = "sqlite"
    warnings: list[str] = Field(default_factory=list)
