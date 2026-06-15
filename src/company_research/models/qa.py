from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class OpenQuestion(BaseModel):
    question_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    question: str
    why_it_matters: str
    best_source: str | None = None
    current_hypothesis: str | None = None
    status: Literal["open", "resolved", "unresolvable"] = "open"


class QAResult(BaseModel):
    qa_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    passed: bool
    critical_failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    checks: dict[str, bool] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
