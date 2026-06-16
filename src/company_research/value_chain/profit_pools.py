"""Profit pool analysis — assembles margin data per value chain layer from XBRL metrics."""
from __future__ import annotations

import logging

from company_research.models.value_chain import ProfitPoolAssessment, ValueChainLayer
from company_research.storage.database import Database

log = logging.getLogger(__name__)


def build_profit_pools(
    layers: list[ValueChainLayer],
    run_id: str,
    db: Database,
) -> list[ProfitPoolAssessment]:
    """
    Build ProfitPoolAssessment stubs for each layer.
    VC-M3 will populate margin/ROIC data from XBRL metrics of representative companies.
    """
    assessments: list[ProfitPoolAssessment] = []
    for layer in layers:
        assessment = ProfitPoolAssessment(
            run_id=run_id,
            layer_name=layer.layer_name,
        )
        db.upsert_vc_profit_pool(assessment)
        assessments.append(assessment)
    log.info("Created %d profit pool stubs for run %s", len(assessments), run_id)
    return assessments
