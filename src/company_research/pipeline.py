from __future__ import annotations

import logging
import subprocess
from datetime import date, datetime
from pathlib import Path

from company_research.analysis.sections import analyze_all_sections
from company_research.config import settings
from company_research.extraction.facts import SECTION_TOPICS, extract_and_store
from company_research.identity.edgar import get_company_facts
from company_research.identity.resolver import resolve
from company_research.llm.anthropic import AnthropicProvider
from company_research.llm.base import ReasoningProvider
from company_research.llm.prompts import prompt_version
from company_research.models.evidence import EvidenceFact
from company_research.models.identity import ResearchRun
from company_research.models.sources import SourceRecord
from company_research.parsing.xbrl import extract_metrics
from company_research.reporting.formatter import write_report
from company_research.reporting.generator import generate_report
from company_research.sources.edgar import EdgarAdapter
from company_research.sources.ir_page import IRPageAdapter
from company_research.sources.peer_selector import PeerSelector
from company_research.sources.product_page import ProductPageAdapter
from company_research.sources.web_search import WebSearchAdapter
from company_research.storage.cache import RawCache
from company_research.storage.database import Database
from company_research.storage.export import export_qa, export_run
from company_research.storage.vectorstore import VectorStore
from company_research.validation.citations import verify_citations
from company_research.validation.qa import run_qa

log = logging.getLogger(__name__)

_LOG_FORMAT = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


def _attach_file_log(log_path: Path) -> logging.FileHandler:
    """Add a FileHandler to the root logger; returns it for later removal."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE_FORMAT))
    logging.getLogger().addHandler(handler)
    return handler


def _detach_file_log(handler: logging.FileHandler) -> None:
    handler.flush()
    handler.close()
    logging.getLogger().removeHandler(handler)


def analyze(
    symbol: str,
    depth: str,
    as_of: date,
    lookback_years: int,
    output_root: Path,
    dry_run: bool = False,
    rag_top_k: int | None = None,
) -> ResearchRun:
    profile = settings.profile(depth)
    out_dir = output_root / symbol.upper() / as_of.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)

    file_handler = _attach_file_log(out_dir / "run.log")
    try:
        return _run(
            symbol=symbol,
            depth=depth,
            as_of=as_of,
            lookback_years=lookback_years,
            output_root=output_root,
            out_dir=out_dir,
            profile=profile,
            dry_run=dry_run,
            rag_top_k=rag_top_k,
        )
    finally:
        _detach_file_log(file_handler)


def _run(
    symbol: str,
    depth: str,
    as_of: date,
    lookback_years: int,
    output_root: Path,
    out_dir: Path,
    profile: dict,
    dry_run: bool,
    rag_top_k: int | None,
) -> ResearchRun:
    db_path = output_root / "research.db"
    cache_root = output_root / ".cache"
    effective_rag_top_k = rag_top_k if rag_top_k is not None else profile.get("rag_top_k", 12)

    db = Database(db_path)
    cache = RawCache(cache_root)
    vector_store = VectorStore(base_dir=output_root, symbol=symbol)

    llm: ReasoningProvider
    if dry_run:
        from company_research.llm.dry_run import DryRunProvider
        prompts_dir = out_dir / "prompts"
        llm = DryRunProvider(prompts_dir=prompts_dir)
    else:
        llm = AnthropicProvider()

    # Log run header — captured in run.log and console
    _log_run_header(
        symbol=symbol,
        depth=depth,
        as_of=as_of,
        lookback_years=lookback_years,
        model_id=settings.model_id,
        dry_run=dry_run,
        rag_top_k=effective_rag_top_k,
        out_dir=out_dir,
    )

    # Step 1: Entity resolution
    log.info("Step 1/12 — Entity resolution")
    log.info("Resolving entity for %s...", symbol)
    company = resolve(symbol)
    db.upsert_company(company)
    log.info(
        "Resolved: %s | exchange=%s | CIK=%s | currency=%s | fiscal_year_end=%s",
        company.issuer_name, company.exchange, company.cik,
        company.currency, company.fiscal_year_end,
    )

    # Create run record
    run = ResearchRun(
        symbol=symbol.upper(),
        depth=depth,
        as_of_date=as_of,
        lookback_years=lookback_years,
        model_id=settings.model_id,
        prompt_version=prompt_version("extract_facts"),
        code_commit=_git_commit(),
        config_hash=settings.config_hash(),
        output_dir=str(out_dir),
    )
    db.insert_run(run)
    log.info("Run created: run_id=%s", run.run_id)

    # Step 1b: External source discovery
    log.info("Step 1b/12 — External source discovery")
    ext_sources: list[SourceRecord] = []

    if profile.get("enable_ir_pages", True):
        ir_adapter = IRPageAdapter(cache=cache, max_pages=profile.get("max_ir_pages", 3))
        try:
            found = ir_adapter.search(company, cutoff=as_of)
            ext_sources.extend(found)
            log.info("IRPageAdapter: %d pages for %s", len(found), company.symbol)
        except Exception as e:
            log.warning("IRPageAdapter failed: %s", e)

    if profile.get("enable_product_pages", False):
        product_adapter = ProductPageAdapter(
            cache=cache, max_pages=profile.get("max_product_pages", 2)
        )
        try:
            found = product_adapter.search(company, cutoff=as_of)
            ext_sources.extend(found)
            log.info("ProductPageAdapter: %d pages for %s", len(found), company.symbol)
        except Exception as e:
            log.warning("ProductPageAdapter failed: %s", e)

    if profile.get("enable_web_search", False):
        web_adapter = WebSearchAdapter(
            cache=cache,
            max_results=profile.get("web_search_results_per_query", 3),
        )
        try:
            found = web_adapter.search(company, cutoff=as_of)
            ext_sources.extend(found)
            log.info("WebSearchAdapter: %d URLs for %s", len(found), company.symbol)
        except Exception as e:
            log.warning("WebSearchAdapter failed: %s", e)

    for src in ext_sources:
        db.upsert_source(src, run.run_id)
    log.info("External sources total: %d", len(ext_sources))

    # Step 1c: Peer selection and peer EDGAR acquisition
    peer_identities: list[CompanyIdentity] = []
    if profile.get("enable_peer_search", True):
        log.info("Step 1c/12 — Peer selection (max_peers=%d)", profile.get("max_competitors", 5))
        peer_selector = PeerSelector(
            cache=cache,
            max_peers=profile.get("max_competitors", 5),
            max_peer_filings=profile.get("max_peer_filings", 3),
        )
        try:
            peer_results = peer_selector.select(company, cutoff=as_of)
            for peer_identity, peer_sources in peer_results:
                peer_identities.append(peer_identity)
                db.upsert_company(peer_identity)
                for ps in peer_sources:
                    db.upsert_source(ps, run.run_id)
                db.upsert_peer(
                    run.run_id,
                    peer_identity.symbol,
                    peer_name=peer_identity.issuer_name,
                    peer_cik=peer_identity.cik,
                )
            if peer_identities:
                company = company.model_copy(
                    update={"peers": [p.symbol for p in peer_identities]}
                )
                db.upsert_company(company)
            log.info("Peer selection complete: %d peers resolved", len(peer_identities))
        except Exception as e:
            log.warning("Peer selection failed: %s", e)
    else:
        log.info("Step 1c/12 — Peer selection skipped (disabled in profile)")

    # Step 2: Source acquisition
    log.info("Step 2/12 — Source acquisition (max_filings=%d)", profile.get("max_filings", 20))
    edgar = EdgarAdapter(cache=cache, max_filings=profile.get("max_filings", 20))
    sources = edgar.search(company, cutoff=as_of)
    log.info("Found %d EDGAR sources after priority sort", len(sources))
    for i, src in enumerate(sources, 1):
        log.debug("  Source %02d: [%s] %s", i, src.source_type, src.title)
    for source in sources:
        db.upsert_source(source, run.run_id)

    # Merge external + EDGAR sources for fetch/parse/index
    sources = ext_sources + sources

    # Shared HTML adapter for fetching external (non-EDGAR) sources
    _html_adapter = WebSearchAdapter(cache=cache, max_results=0)

    # Step 3+4: Fetch, parse, index
    log.info("Step 3+4/12 — Fetch, parse, and vector-index %d sources", len(sources))
    indexed, skipped = 0, 0
    for source in sources:
        log.info("Fetching [%s] %s", source.source_type, source.title)
        try:
            _adapter = edgar if source.reliability_tier == 1 else _html_adapter
            raw_doc = _adapter.fetch(source)
            is_new = db.upsert_document(raw_doc)
            cache_tag = "new" if is_new else "cached"
            log.debug("Document %s (%s, %d bytes)", source.source_id, cache_tag, raw_doc.size_bytes)
            norm_doc = _adapter.normalize(raw_doc)
            n_chunks = vector_store.index_document(
                doc_id=norm_doc.doc_id,
                text=norm_doc.text,
                metadata={
                    "source_id": source.source_id,
                    "title": source.title,
                    "source_type": source.source_type,
                    "period_covered": source.period_covered or "",
                    "published_date": source.published_date.isoformat() if source.published_date else "",
                },
            )
            log.info("Indexed %d chunks from %s (%s)", n_chunks, source.source_type, source.source_id)
            indexed += 1
        except Exception as e:
            log.error("Failed to fetch/parse/index %s: %s", source.url, e)
            skipped += 1

    log.info(
        "Indexing complete: %d indexed, %d skipped — vector store total=%d chunks",
        indexed, skipped, vector_store.count,
    )

    # Step 5: XBRL metrics
    log.info("Step 5/12 — XBRL financial metric extraction")
    try:
        company_facts = get_company_facts(company.cik)
        xbrl_source = SourceRecord(
            title=f"{company.issuer_name} XBRL Company Facts",
            publisher="SEC EDGAR",
            url=f"https://data.sec.gov/api/xbrl/companyfacts/CIK{company.cik}.json",
            source_type="10-K",
            primary_or_secondary="primary",
            company_or_external="regulator",
            reliability_tier=1,
        )
        db.upsert_source(xbrl_source, run.run_id)
        metrics = extract_metrics(
            company_facts=company_facts,
            run_id=run.run_id,
            source_id=xbrl_source.source_id,
            cutoff_year=as_of.year,
            lookback_years=lookback_years,
        )
        for metric in metrics:
            db.insert_metric(metric)
        log.info("Stored %d XBRL metric observations", len(metrics))
    except Exception as e:
        log.warning("XBRL extraction failed: %s", e)

    # Step 6: RAG fact extraction
    target_sections = profile.get("sections", ["company_snapshot"])
    if isinstance(target_sections, str) and target_sections == "all":
        target_sections = list(SECTION_TOPICS.keys())

    log.info(
        "Step 6/12 — RAG fact extraction | sections=%d | rag_top_k=%d",
        len(target_sections), effective_rag_top_k,
    )
    all_facts: list[EvidenceFact] = []
    for section in target_sections:
        try:
            facts = extract_and_store(
                vector_store=vector_store,
                context=company,
                run_id=run.run_id,
                db=db,
                llm=llm,
                section=section,
                k=effective_rag_top_k,
            )
            all_facts.extend(facts)
            log.debug("Section '%s' → %d facts (running total=%d)", section, len(facts), len(all_facts))
        except Exception as e:
            log.error("Fact extraction failed for section '%s': %s", section, e)

    log.info("Fact extraction complete: %d facts across %d sections", len(all_facts), len(target_sections))

    # Step 7: Contradiction detection
    log.info("Step 7/12 — Contradiction detection (%d facts)", len(all_facts))
    if all_facts:
        try:
            contradictions = llm.detect_counterevidence(all_facts, run.run_id)
            for c in contradictions:
                db.insert_contradiction(c)
            log.info("Detected %d contradictions", len(contradictions))
        except Exception as e:
            log.error("Contradiction detection failed: %s", e)
    else:
        log.warning("No facts available — skipping contradiction detection")

    # Step 8: Citation verification
    log.info("Step 8/12 — Citation verification")
    try:
        verified, failed = verify_citations(run.run_id, db, cache)
        log.info("Citations: %d verified, %d failed", verified, failed)
    except Exception as e:
        log.error("Citation verification failed: %s", e)

    # Step 9: Section analysis
    log.info("Step 9/12 — Section analysis (%d sections)", len(target_sections))
    analyze_all_sections(
        sections=target_sections,
        facts=all_facts,
        run=run,
        db=db,
        llm=llm,
    )

    # Step 10: Report generation
    log.info("Step 10/12 — Report generation")
    try:
        report_md = generate_report(run=run, company=company, db=db, llm=llm)
        db_sources = db.get_sources(run.run_id)
        write_report(report_md=report_md, sources=db_sources, out_dir=out_dir)
        report_path = out_dir / "report.md"
        log.info(
            "Report written: %s (%d chars, %d words)",
            report_path, len(report_md), len(report_md.split()),
        )
    except Exception as e:
        log.error("Report generation failed: %s", e)

    # Step 11: QA
    log.info("Step 11/12 — QA checks")
    qa_result = run_qa(run.run_id, db, out_dir=out_dir)
    for check, passed in qa_result.checks.items():
        level = logging.INFO if passed else logging.WARNING
        log.log(level, "  QA %-40s %s", check, "PASS" if passed else "FAIL")

    # Step 12: Export
    log.info("Step 12/12 — Export to %s", out_dir)
    export_run(run.run_id, db, out_dir)
    export_qa(qa_result, out_dir)

    status = "completed" if qa_result.passed else "partial"
    db.update_run_status(run.run_id, status, datetime.utcnow().isoformat())
    run.status = status
    run.completed_at = datetime.utcnow()

    if qa_result.passed:
        log.info("=== Run COMPLETED (run_id=%s) ===", run.run_id)
    else:
        log.warning(
            "=== Run PARTIAL (run_id=%s) — QA failures: %s ===",
            run.run_id, "; ".join(qa_result.critical_failures),
        )

    return run


def _log_run_header(
    symbol: str,
    depth: str,
    as_of: date,
    lookback_years: int,
    model_id: str,
    dry_run: bool,
    rag_top_k: int,
    out_dir: Path,
) -> None:
    sep = "=" * 60
    log.info(sep)
    log.info("  company-research run")
    log.info("  Symbol:       %s", symbol.upper())
    log.info("  Depth:        %s", depth)
    log.info("  As-of:        %s", as_of)
    log.info("  Lookback:     %dy", lookback_years)
    log.info("  RAG top-k:    %d", rag_top_k)
    log.info("  Model:        %s", model_id)
    log.info("  Dry-run:      %s", dry_run)
    log.info("  Started:      %s", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"))
    log.info("  Output:       %s", out_dir)
    log.info(sep)
