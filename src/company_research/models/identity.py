from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class CompanyIdentity(BaseModel):
    symbol: str
    exchange: str
    issuer_name: str
    cik: str  # zero-padded 10-digit SEC CIK
    lei: str | None = None
    isin: str | None = None
    fiscal_year_end: str  # MM-DD, e.g. "09-30"
    currency: str  # ISO 4217, e.g. "USD"
    ir_url: str | None = None
    filing_jurisdiction: str  # e.g. "US", "foreign_private_issuer"
    peers: list[str] = Field(default_factory=list)  # resolved peer ticker symbols
    security_type: Literal[
        "operating_company", "ADR", "fund", "shell", "partnership", "unknown"
    ] = "unknown"

    @field_validator("cik")
    @classmethod
    def pad_cik(cls, v: str) -> str:
        return v.strip().zfill(10)

    @field_validator("symbol")
    @classmethod
    def upper_symbol(cls, v: str) -> str:
        return v.strip().upper()


class ResearchRun(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    depth: Literal["quick", "standard", "deep"]
    as_of_date: date
    lookback_years: int = 5
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    status: Literal["running", "completed", "failed", "partial"] = "running"
    model_id: str
    prompt_version: str
    code_commit: str
    config_hash: str
    output_dir: str
