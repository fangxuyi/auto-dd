"""Value chain decomposer — defines layers and internal vs outsourced activities."""
from __future__ import annotations

import logging
from datetime import date

from company_research.models.identity import CompanyIdentity
from company_research.models.value_chain import ValueChainLayer
from company_research.storage.database import Database
from company_research.value_chain.templates import infer_template, load_template

log = logging.getLogger(__name__)


def decompose(
    company: CompanyIdentity,
    run_id: str,
    db: Database,
    template_name: str | None = None,
) -> tuple[list[ValueChainLayer], dict]:
    """
    Build the initial value chain layer structure for a company.

    Returns (layers, template_dict). Layers are stored in the DB.
    template_name overrides auto-inference when supplied.
    """
    name = template_name or infer_template(
        sic_code=None, issuer_name=company.issuer_name
    )
    log.info("Using value chain template '%s' for %s", name, company.symbol)
    template = load_template(name)

    layers: list[ValueChainLayer] = []
    for layer_def in template.get("layers", []):
        layer = ValueChainLayer(
            run_id=run_id,
            symbol=company.symbol,
            layer_name=layer_def["name"],
            description=layer_def.get("description", ""),
            order=layer_def.get("order", 0),
        )
        layers.append(layer)
        db.upsert_vc_layer(layer)

    log.info("Decomposed %d value chain layers for %s", len(layers), company.symbol)
    return layers, template
