"""Models for research diffs — tracking what changed between runs."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class MetricChange(BaseModel):
    name: str
    period: str
    unit: str
    prior_value: float | None = None
    new_value: float | None = None
    change_pct: float | None = None  # None when prior is zero or unavailable


class FactChange(BaseModel):
    topic: str
    change_type: Literal["new", "changed", "removed"]
    prior_claim: str | None = None
    new_claim: str | None = None
    source_id: str | None = None


class ConclusionChange(BaseModel):
    section: str
    change_type: Literal["new", "changed", "same"]
    prior_conclusion: str | None = None
    new_conclusion: str | None = None
    prior_confidence: str | None = None
    new_confidence: str | None = None


class ResearchDiff(BaseModel):
    diff_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    prior_run_id: str
    new_run_id: str
    prior_date: date
    new_date: date
    new_sources_count: int = 0
    new_facts: list[FactChange] = Field(default_factory=list)
    changed_metrics: list[MetricChange] = Field(default_factory=list)
    changed_conclusions: list[ConclusionChange] = Field(default_factory=list)
    new_risks: list[str] = Field(default_factory=list)
    invalidated_assumptions: list[str] = Field(default_factory=list)


class MonitoringIndicator(BaseModel):
    section: str
    indicator: str
    run_id: str
    symbol: str
    as_of_date: date


class MonitoringDashboard(BaseModel):
    symbol: str
    as_of_date: date
    run_id: str
    indicators: list[MonitoringIndicator] = Field(default_factory=list)
