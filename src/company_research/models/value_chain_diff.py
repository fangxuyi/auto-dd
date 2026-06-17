"""Models for value chain graph diffs and monitoring indicators."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from company_research.models.value_chain import Materiality, RelationshipType, VCConfidence


class VCRelationshipChange(BaseModel):
    change_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    change_type: Literal[
        "added", "removed", "status_changed", "confidence_changed", "materiality_changed"
    ]
    entity_name: str
    relationship_type: RelationshipType
    product_or_service: str | None = None
    prior_status: str | None = None
    new_status: str | None = None
    prior_confidence: VCConfidence | None = None
    new_confidence: VCConfidence | None = None
    prior_materiality: Materiality | None = None
    new_materiality: Materiality | None = None
    notes: str = ""


class VCGraphDiff(BaseModel):
    diff_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    prior_run_id: str
    new_run_id: str
    as_of_date: date
    changes: list[VCRelationshipChange] = Field(default_factory=list)
    new_node_names: list[str] = Field(default_factory=list)
    removed_node_names: list[str] = Field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.changes or self.new_node_names or self.removed_node_names)


class VCMonitoringIndicator(BaseModel):
    indicator_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    symbol: str
    entity_name: str
    relationship_type: str
    indicator: str
    trigger: str
    urgency: Literal["high", "medium", "low"] = "medium"
