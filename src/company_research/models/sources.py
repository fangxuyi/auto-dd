from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


SourceType = Literal[
    "10-K", "10-Q", "8-K", "DEF14A", "20-F", "6-K", "Form4", "13D", "13G",
    "S-1", "earnings_release", "ir_page", "product_page", "pricing_page",
    "press_release", "investor_presentation", "news_article", "web_search",
    "other",
]


class SourceRecord(BaseModel):
    source_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    publisher: str
    url: str
    published_date: date | None = None
    accessed_date: datetime = Field(default_factory=datetime.utcnow)
    source_type: SourceType
    primary_or_secondary: Literal["primary", "secondary"] = "secondary"
    period_covered: str | None = None  # e.g. "FY2024", "Q3_2024"
    company_or_external: Literal["company", "external", "regulator"] = "external"
    reliability_tier: int = Field(ge=1, le=8, default=8)
    is_peer: bool = False  # True for peer/competitor filings; indexed into separate collection


class RawDocument(BaseModel):
    doc_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_id: str
    content_hash: str  # sha256 hex
    file_path: str     # absolute path in content-addressed cache
    mime_type: str
    size_bytes: int
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)


class TableCell(BaseModel):
    text: str
    row: int
    col: int


class DocumentSection(BaseModel):
    heading: str
    text: str
    char_offset: int  # character offset in full document text


class DocumentTable(BaseModel):
    caption: str | None = None
    headers: list[str]
    rows: list[list[str]]
    page: int | None = None
    char_offset: int | None = None


class NormalizedDocument(BaseModel):
    doc_id: str
    source_id: str
    text: str
    sections: list[DocumentSection] = Field(default_factory=list)
    tables: list[DocumentTable] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
