"""Value chain pipeline — orchestrates VC-M1 through VC-M4 analysis."""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from company_research.models.identity import CompanyIdentity, ResearchRun
from company_research.models.value_chain import PublicEntityIdentity
from company_research.storage.cache import RawCache
from company_research.storage.database import Database
from company_research.value_chain.chokepoints import identify_chokepoints
from company_research.value_chain.decompose import decompose
from company_research.value_chain.dependency import assess_dependency
from company_research.value_chain.discovery import discover_from_sources
from company_research.value_chain.edgar_reverse import discover_reverse_mentions
from company_research.value_chain.graph import build_graph, export_graph
from company_research.value_chain.product_extraction import extract_products
from company_research.value_chain.profit_pools import build_profit_pools
from company_research.value_chain.relationships import build_relationships
from company_research.value_chain.reporting import write_value_chain_report
from company_research.value_chain.validation import run_vc_qa
from company_research.value_chain.verification import resolve_candidates

log = logging.getLogger(__name__)


def run_value_chain(
    symbol: str,
    depth: str,
    as_of: date,
    output_root: Path,
    template_name: str | None = None,
) -> dict:
    """
    Main value chain pipeline entry point.

    Requires that `company-research analyze SYMBOL` has been run first (for
    entity resolution and EDGAR source caching).

    Steps:
      VC-1   Load entity and prior run context
      VC-2   Decompose into industry template layers
      VC-3   Discover candidates from cached EDGAR sources (forward)
      VC-3b  Reverse EDGAR lookup — companies whose filings mention the target
      VC-4   Resolve candidates to public entities (exact ticker + fuzzy name)
      VC-5   Build relationship records
      VC-6   Assess dependency / bargaining power
      VC-7   Build profit pool stubs
      VC-8   Identify chokepoints
      VC-9   Assemble graph
      VC-10  Write report and exports
      VC-11  QA
    """
    db_path = output_root / "research.db"
    cache_root = output_root / ".cache"
    db = Database(db_path)
    cache = RawCache(cache_root)

    out_dir = output_root / symbol.upper() / as_of.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)

    # VC-1: load prior run context
    prior_run = db.get_latest_run(symbol)
    if prior_run is None:
        raise RuntimeError(
            f"No prior research run found for {symbol}. "
            "Run 'company-research analyze {symbol}' first."
        )
    run_id = prior_run["run_id"]
    log.info("Using run_id=%s for value chain analysis of %s", run_id, symbol)

    # Reconstruct company identity from DB
    with db._conn() as conn:
        row = conn.execute(
            "SELECT * FROM companies WHERE symbol=?", (symbol.upper(),)
        ).fetchone()
    if row is None:
        raise RuntimeError(f"No company record found for {symbol} in DB.")
    company_row = dict(row)

    company = CompanyIdentity(
        symbol=company_row["symbol"],
        exchange=company_row["exchange"],
        issuer_name=company_row["issuer_name"],
        cik=company_row["cik"],
        fiscal_year_end=company_row["fiscal_year_end"],
        currency=company_row["currency"],
        ir_url=company_row.get("ir_url"),
        filing_jurisdiction=company_row["filing_jurisdiction"],
        security_type=company_row.get("security_type", "unknown"),
    )

    # Register target company as a VC entity
    target_entity = PublicEntityIdentity(
        legal_name=company.issuer_name,
        common_name=company.symbol,
        ticker=company.symbol,
        regulator_id=company.cik,
        active_listing=True,
        as_of_date=as_of,
    )
    db.upsert_vc_entity(target_entity)

    # VC-2: decompose into layers
    log.info("VC-2: Decomposing value chain layers")
    layers, template = decompose(company, run_id, db, template_name=template_name)

    # VC-3: discover candidates from cached sources (forward — target's own filings)
    log.info("VC-3: Discovering relationship candidates from EDGAR sources")
    candidates = discover_from_sources(run_id=run_id, db=db, cache=cache)
    for c in candidates:
        db.upsert_vc_candidate(c)
    log.info("Stored %d forward candidates", len(candidates))

    # VC-3b: reverse EDGAR lookup — find filers that name our target company
    log.info("VC-3b: Reverse EDGAR lookup for '%s' mentions", company.issuer_name)
    reverse_candidates = discover_reverse_mentions(
        company_name=company.issuer_name,
        run_id=run_id,
        as_of=as_of,
        db=db,
        target_cik=company.cik,
    )
    for c in reverse_candidates:
        db.upsert_vc_candidate(c)
    candidates.extend(reverse_candidates)
    log.info(
        "Total candidates after reverse lookup: %d (%d forward + %d reverse)",
        len(candidates), len(candidates) - len(reverse_candidates), len(reverse_candidates),
    )

    # VC-4: resolve candidates to public entities (exact ticker + fuzzy name fallback)
    log.info("VC-4: Resolving candidates to EDGAR entities")
    resolved_pairs = resolve_candidates(candidates, db, max_resolve=200)
    resolved_count = sum(1 for _, e in resolved_pairs if e is not None)
    log.info("Resolved %d / %d candidates", resolved_count, len(resolved_pairs))

    # Collect entity map (pre-resolved reverse candidates are returned with entity populated)
    entities: dict[str, PublicEntityIdentity] = {target_entity.entity_id: target_entity}
    for candidate, entity in resolved_pairs:
        if entity is not None:
            entities[entity.entity_id] = entity

    # VC-5: build relationships
    log.info("VC-5: Building relationship records")
    relationships = build_relationships(
        target=company,
        target_entity_id=target_entity.entity_id,
        resolved_pairs=resolved_pairs,
        run_id=run_id,
        db=db,
        as_of=as_of,
    )

    # VC-5b: extract product/service labels via Haiku 4.5
    log.info("VC-5b: Extracting product/service labels")
    extract_products(relationships, db, target_name=company.issuer_name)

    # VC-6: dependency assessments
    log.info("VC-6: Assessing dependencies")
    dependencies = [assess_dependency(rel, run_id, db) for rel in relationships]

    # VC-7: profit pools
    log.info("VC-7: Building profit pool stubs")
    profit_pools = build_profit_pools(layers, run_id, db)

    # VC-8: chokepoints
    log.info("VC-8: Identifying chokepoints")
    chokepoints = identify_chokepoints(relationships, dependencies, run_id, db)

    # VC-9: graph assembly
    log.info("VC-9: Assembling value chain graph")
    graph = build_graph(
        run_id=run_id,
        symbol=symbol.upper(),
        as_of=as_of,
        relationships=relationships,
        entities=entities,
    )
    export_graph(graph, out_dir)

    # VC-10: report
    log.info("VC-10: Writing value chain report")
    write_value_chain_report(
        symbol=symbol.upper(),
        as_of=as_of,
        graph=graph,
        profit_pools=profit_pools,
        chokepoints=chokepoints,
        out_dir=out_dir,
    )

    # VC-11: QA
    log.info("VC-11: Running value chain QA")
    qa = run_vc_qa(graph, relationships)
    log.info("VC QA: passed=%s failures=%s", qa.passed, qa.critical_failures)

    return {
        "run_id": run_id,
        "symbol": symbol.upper(),
        "as_of_date": as_of.isoformat(),
        "template": template.get("name", "unknown"),
        "layers": len(layers),
        "candidates_discovered": len(candidates),
        "candidates_resolved": resolved_count,
        "relationships": len(relationships),
        "graph_nodes": len(graph.nodes),
        "graph_edges": len(graph.edges),
        "confirmed_edges": len(graph.confirmed_edges),
        "chokepoints": len(chokepoints),
        "qa_passed": qa.passed,
        "qa_failures": qa.critical_failures,
    }
