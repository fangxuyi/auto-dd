from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field


FactTopic = Literal[
    "business_model", "revenue", "customers", "product", "competition",
    "management", "financials", "market", "risk", "governance", "other",
]

Confidence = Literal["high", "medium", "low", "unknown"]
FactType = Literal["fact", "claim", "inference"]
ExtractionMethod = Literal["llm", "xbrl_parser", "html_parser", "manual"]


class EvidenceFact(BaseModel):
    fact_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    topic: FactTopic
    claim: str
    value: str | None = None
    unit: str | None = None
    period: str | None = None  # e.g. "FY2024", "Q3_2024", "as_of_2024-09-30"
    source_id: str
    source_location: str  # e.g. "Item 1, p.4" or "MD&A, Revenue section"
    fact_claim_or_inference: FactType = "fact"
    extraction_method: ExtractionMethod = "llm"
    confidence: Confidence = "medium"
    notes: str | None = None


class MetricObservation(BaseModel):
    metric_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    name: str          # e.g. "revenue", "gross_margin", "net_income"
    value: float
    unit: str          # e.g. "USD_millions", "percent"
    period: str        # e.g. "FY2024", "Q3_2024"
    period_type: Literal["fiscal", "calendar"]
    value_type: Literal["reported", "calculated", "estimated", "consensus"]
    currency: str | None = None  # ISO 4217
    source_id: str
    notes: str | None = None
