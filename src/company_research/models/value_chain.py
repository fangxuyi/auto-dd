"""Value chain and public-company relationship models."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


# ── evidence and status types ─────────────────────────────────────────────────

RelationshipType = Literal[
    "SUPPLIES",
    "CONTRACT_MANUFACTURES_FOR",
    "HOSTS",
    "PROVIDES_DATA_TO",
    "LICENSES_IP_TO",
    "DISTRIBUTES",
    "RESELLS",
    "INTEGRATES",
    "MARKETPLACE_FOR",
    "LOGISTICS_PROVIDER_TO",
    "PAYMENT_PROVIDER_TO",
    "CUSTOMER_OF",
    "OEM_CUSTOMER_OF",
    "CHANNEL_PARTNER_OF",
    "COMPLEMENTS",
    "SUBSTITUTES_FOR",
    "COMPETES_WITH",
    "INVESTS_IN",
    "JOINT_VENTURE_WITH",
    "HISTORICAL_RELATIONSHIP",
    "CATEGORY_PARTICIPANT",
]

EvidenceStatus = Literal[
    "confirmed_primary",
    "confirmed_secondary",
    "inferred",
    "historical",
    "unverified",
    "contradicted",
]

RelationshipStatus = Literal[
    "confirmed_direct",
    "confirmed_category_participant",
    "inferred_likely",
    "historical",
    "unverified_candidate",
    "contradicted",
]

VCConfidence = Literal["high", "medium", "low", "unknown"]

Materiality = Literal["critical", "significant", "moderate", "minor", "unknown"]


# ── value chain layer ─────────────────────────────────────────────────────────


class ValueChainLayer(BaseModel):
    layer_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    symbol: str
    layer_name: str           # e.g. "upstream", "company", "downstream", "complementors", "substitutes"
    description: str = ""
    order: int = 0            # lower = further upstream


# ── entity models ─────────────────────────────────────────────────────────────


class PublicEntityIdentity(BaseModel):
    """A verified public-company entity with listing details."""
    entity_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    legal_name: str
    common_name: str = ""
    ticker: str | None = None
    exchange: str | None = None
    country: str | None = None
    security_type: Literal["operating_company", "ADR", "fund", "holding", "other", "unknown"] = "unknown"
    primary_listing: bool = True
    adr_status: bool = False
    operating_subsidiary: str | None = None
    ultimate_public_parent: str | None = None   # ticker of ultimate listed parent
    regulator_id: str | None = None             # CIK for US companies
    isin: str | None = None
    active_listing: bool = True
    as_of_date: date | None = None
    aliases: list[str] = Field(default_factory=list)


class EntityCandidate(BaseModel):
    """Unverified relationship candidate prior to resolution."""
    candidate_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    raw_name: str                       # name string as found in source
    normalized_name: str = ""
    source_id: str | None = None
    source_excerpt: str | None = None
    proposed_layer: str | None = None
    proposed_relationship_type: RelationshipType | None = None
    resolved_entity_id: str | None = None
    resolution_status: Literal["unresolved", "resolved", "ambiguous", "rejected"] = "unresolved"


# ── relationship evidence ─────────────────────────────────────────────────────


class RelationshipEvidence(BaseModel):
    evidence_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    relationship_id: str
    source_id: str
    source_location: str = ""
    excerpt: str | None = None
    evidence_status: EvidenceStatus = "unverified"
    direction: Literal["target_first", "counterparty_first", "independent"] = "target_first"
    verified_date: date | None = None


# ── relationship ──────────────────────────────────────────────────────────────


class CompanyRelationship(BaseModel):
    """A directional relationship between the target company and another entity."""
    relationship_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    source_entity_id: str           # the entity that provides / sells / manufactures
    target_entity_id: str           # the entity that receives / buys / distributes
    relationship_type: RelationshipType
    value_chain_layer: str | None = None
    product_or_service: str | None = None
    geography: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    current_status: RelationshipStatus = "unverified_candidate"
    evidence_status: EvidenceStatus = "unverified"
    confidence: VCConfidence = "unknown"
    materiality: Materiality = "unknown"
    exclusivity: bool | None = None
    source_ids: list[str] = Field(default_factory=list)
    source_locations: list[str] = Field(default_factory=list)
    last_verified_date: date | None = None
    analyst_notes: str | None = None
    reverse_verified: bool = False    # True if counterparty's sources also confirm


# ── dependency and bargaining power ──────────────────────────────────────────


class DependencyAssessment(BaseModel):
    assessment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    relationship_id: str
    target_dependency_score: int | None = None   # 1=easily replaceable … 5=critical bottleneck
    counterparty_dependency_score: int | None = None
    target_dependency_rationale: str = ""
    counterparty_dependency_rationale: str = ""
    switching_cost_notes: str = ""
    alternatives_exist: bool | None = None
    qualification_time_months: int | None = None
    contract_duration_months: int | None = None
    confidence: VCConfidence = "unknown"


# ── profit pool ───────────────────────────────────────────────────────────────


class ProfitPoolAssessment(BaseModel):
    assessment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    layer_name: str
    representative_companies: list[str] = Field(default_factory=list)  # tickers
    gross_margin_range: str | None = None           # e.g. "40–60%"
    operating_margin_range: str | None = None
    roic_range: str | None = None
    capital_intensity: Literal["high", "medium", "low", "unknown"] = "unknown"
    concentration: Literal["concentrated", "fragmented", "moderate", "unknown"] = "unknown"
    pricing_power: Literal["strong", "moderate", "weak", "unknown"] = "unknown"
    trend: Literal["improving", "stable", "declining", "unknown"] = "unknown"
    notes: str = ""


# ── chokepoint ────────────────────────────────────────────────────────────────


class ChokepointAssessment(BaseModel):
    chokepoint_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    chokepoint: str                     # what the bottleneck is
    owner_or_controller: str | None = None
    affected_product: str | None = None
    failure_mechanism: str = ""
    replacement_time: str | None = None
    financial_effect: str | None = None
    early_warning_indicators: list[str] = Field(default_factory=list)
    mitigation: str | None = None
    confidence: VCConfidence = "unknown"


# ── graph models ──────────────────────────────────────────────────────────────


class GraphNode(BaseModel):
    node_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    entity_id: str
    entity_name: str
    entity_type: str = ""
    public_status: Literal["public", "private", "unknown"] = "unknown"
    ticker: str | None = None
    exchange: str | None = None
    country: str | None = None
    industry: str | None = None
    value_chain_layers: list[str] = Field(default_factory=list)
    ultimate_public_parent: str | None = None


class GraphEdge(BaseModel):
    edge_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    source_node_id: str
    target_node_id: str
    relationship_type: RelationshipType
    product_or_service: str | None = None
    status: RelationshipStatus = "unverified_candidate"
    confidence: VCConfidence = "unknown"
    materiality: Materiality = "unknown"
    start_date: date | None = None
    end_date: date | None = None
    source_ids: list[str] = Field(default_factory=list)
    last_verified_date: date | None = None
    source_excerpt: str | None = None


class ValueChainGraph(BaseModel):
    graph_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    symbol: str
    as_of_date: date
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)

    @property
    def confirmed_edges(self) -> list[GraphEdge]:
        return [
            e for e in self.edges
            if e.status in ("confirmed_direct", "confirmed_category_participant")
        ]
