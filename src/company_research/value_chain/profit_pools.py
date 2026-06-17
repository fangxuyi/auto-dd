"""Profit pool analysis — assembles margin data per value chain layer from XBRL metrics."""
from __future__ import annotations

import logging

from company_research.models.value_chain import (
    CompanyRelationship,
    ProfitPoolAssessment,
    ValueChainLayer,
)
from company_research.storage.database import Database

log = logging.getLogger(__name__)

_UPSTREAM_LAYER_HINTS = {"upstream", "supplier", "input", "component", "raw material"}
_DOWNSTREAM_LAYER_HINTS = {"downstream", "customer", "distribution", "channel", "retail"}
_OWN_LAYER_HINTS = {"company", "target", "core", "own"}


def _layer_category(layer_name: str) -> str:
    name = layer_name.lower()
    if any(h in name for h in _OWN_LAYER_HINTS):
        return "own"
    if any(h in name for h in _UPSTREAM_LAYER_HINTS):
        return "upstream"
    if any(h in name for h in _DOWNSTREAM_LAYER_HINTS):
        return "downstream"
    return "other"


def _compute_margin_range(metrics_by_name: dict[str, list[dict]]) -> tuple[str | None, str | None]:
    """Return (gross_margin_range, operating_margin_range) from metric rows."""
    rev_rows = metrics_by_name.get("revenue") or metrics_by_name.get("Revenues") or []
    gp_rows = metrics_by_name.get("gross_profit") or metrics_by_name.get("GrossProfit") or []
    op_rows = metrics_by_name.get("operating_income") or metrics_by_name.get("OperatingIncomeLoss") or []

    def _latest_value(rows: list[dict]) -> float | None:
        annual = [r for r in rows if r.get("period_type") == "annual"]
        candidates = annual or rows
        candidates = sorted(candidates, key=lambda r: r.get("period", ""), reverse=True)
        for r in candidates:
            try:
                return float(r["value"])
            except (TypeError, ValueError, KeyError):
                continue
        return None

    rev = _latest_value(rev_rows)
    gp = _latest_value(gp_rows)
    op = _latest_value(op_rows)

    gm_range = None
    om_range = None
    if rev and rev > 0:
        if gp is not None:
            gm = round(gp / rev * 100, 1)
            gm_range = f"{gm}%"
        if op is not None:
            om = round(op / rev * 100, 1)
            om_range = f"{om}%"
    return gm_range, om_range


def build_profit_pools(
    layers: list[ValueChainLayer],
    run_id: str,
    db: Database,
    relationships: list[CompanyRelationship] | None = None,
) -> list[ProfitPoolAssessment]:
    """
    Build ProfitPoolAssessment for each layer.
    - For the own-company layer: computes gross/operating margin from XBRL metrics in the run.
    - For other layers: populates representative_companies from resolved relationships.
    """
    # Fetch all metrics for this run once
    all_metrics = db.get_metrics(run_id)
    metrics_by_name: dict[str, list[dict]] = {}
    for m in all_metrics:
        metrics_by_name.setdefault(m["name"], []).append(m)

    # Build a set of resolved tickers per layer category from relationships
    tickers_by_category: dict[str, set[str]] = {"upstream": set(), "downstream": set(), "other": set()}
    if relationships:
        for rel in relationships:
            if rel.current_status in ("unverified_candidate", "contradicted"):
                continue
            layer = rel.value_chain_layer or ""
            cat = _layer_category(layer)
            # Try to resolve entity ticker from DB
            for eid in (rel.source_entity_id, rel.target_entity_id):
                entity = db.get_vc_entity(eid)
                if entity and entity.get("ticker"):
                    tickers_by_category.setdefault(cat, set()).add(entity["ticker"])

    assessments: list[ProfitPoolAssessment] = []
    for layer in layers:
        cat = _layer_category(layer.layer_name)
        assessment = ProfitPoolAssessment(
            run_id=run_id,
            layer_name=layer.layer_name,
        )

        if cat == "own":
            # Own-company layer: compute from XBRL in this run
            gm, om = _compute_margin_range(metrics_by_name)
            assessment.gross_margin_range = gm
            assessment.operating_margin_range = om
            if gm or om:
                assessment.notes = "Computed from XBRL metrics in this research run."
            else:
                assessment.notes = "XBRL metrics not available in this run."
        else:
            # Other layers: list representative companies from resolved relationships
            reps = sorted(tickers_by_category.get(cat, set()))[:5]
            assessment.representative_companies = reps
            if reps:
                assessment.notes = (
                    f"Representative companies: {', '.join(reps)}. "
                    "Cross-company XBRL margin data requires separate peer runs."
                )
            else:
                assessment.notes = "No representative public companies resolved for this layer."

        db.upsert_vc_profit_pool(assessment)
        assessments.append(assessment)

    log.info("Built %d profit pool assessments for run %s", len(assessments), run_id)
    return assessments
