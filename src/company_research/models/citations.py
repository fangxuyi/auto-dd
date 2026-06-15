from __future__ import annotations

import uuid
from pydantic import BaseModel, Field


class Citation(BaseModel):
    citation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    fact_id: str
    source_id: str
    location: str   # e.g. "Item 1, p.4", "MD&A §Revenue", "PDF p.12", "speaker/00:04:32"
    quote: str | None = None
    verified: bool = False  # True when quote is found verbatim in source text
