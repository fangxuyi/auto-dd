from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from company_research.models.evidence import Confidence


class Contradiction(BaseModel):
    contradiction_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    fact_id_a: str
    fact_id_b: str
    description: str
    severity: Literal["material", "minor"]
    resolution: str | None = None
    resolved: bool = False


class SectionConclusion(BaseModel):
    conclusion_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    section: str
    conclusion: str
    supporting_fact_ids: list[str] = Field(default_factory=list)
    counterevidence: str | None = None
    confidence: Confidence = "medium"
    open_questions: list[str] = Field(default_factory=list)
    monitoring_indicators: list[str] = Field(default_factory=list)
