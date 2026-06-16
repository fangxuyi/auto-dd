from __future__ import annotations

import logging
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Any

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
from company_research.pipeline_flow import RunFlowRecorder
from company_research.pipeline_update import build_monitoring_dashboard
from company_research.storage.cache import RawCache
from company_research.storage.database import Database
from company_research.storage.export import export_flow, export_monitoring, export_qa, export_run
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
    chunk_size = profile.get("chunk_size", 2800)
    chunk_overlap = profile.get("chunk_overlap", 350)
    # Own-company docs (10-Ks, IR pages, web search about target)
    vector_store = VectorStore(
        base_dir=output_root, symbol=symbol,
        chunk_size=chunk_size, chunk_overlap=chunk_overlap,
    )
    # Peer/competitor filings — separate collection, not used for report generation
    peer_vector_store = VectorStore(
        base_dir=output_root, symbol=symbol + "_peers",
        chunk_size=chunk_size, chunk_overlap=chunk_overlap,
    )

    llm: ReasoningProvider
    if dry_run:
        from company_research.llm.dry_run import DryRunProvider
        prompts_dir = out_dir / "prompts"
        llm = DryRunProvider(prompts_dir=prompts_dir)
    else:
        llm = AnthropicProvider(log_dir=out_dir)

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

    # Create run record (needed for run_id before flow recorder)
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

    flow = RunFlowRecorder(
        run_id=run.run_id,
        symbol=symbol.upper(),
        depth=depth,
        as_of_date=as_of.isoformat(),
        dry_run=dry_run,
        model_id=settings.model_id,
    )

    # Step 1: Entity resolution
    log.info("Step 1/12 — Entity resolution")
    s1 = flow.begin("1", "Entity Resolution")
    log.info("Resolving entity for %s...", symbol)
    company = resolve(symbol)
    db.upsert_company(company)
    log.info(
        "Resolved: %s | exchange=%s | CIK=%s | currency=%s | fiscal_year_end=%s",
        company.issuer_name, company.exchange, company.cik,
        company.currency, company.fiscal_year_end,
    )
    s1.finish(
        issuer_name=company.issuer_name,
        cik=company.cik,
        exchange=company.exchange,
        ir_url=company.ir_url or "not found in EDGAR",
    )

    db.insert_run(run)
    log.info("Run created: run_id=%s", run.run_id)
    log.info("Flow recorder initialised")

    # Step 1b: External source discovery
    log.info("Step 1b/12 — External source discovery")
    s1b = flow.begin("1b", "External Source Discovery")
    ext_sources: list[SourceRecord] = []
    s1b_sub: list[dict] = []

    if profile.get("enable_ir_pages", True):
        ir_adapter = IRPageAdapter(cache=cache, max_pages=profile.get("max_ir_pages", 3))
        try:
            found = ir_adapter.search(company, cutoff=as_of)
            ext_sources.extend(found)
            log.info("IRPageAdapter: %d pages for %s", len(found), company.symbol)
            s1b_sub.append({"adapter": "IRPageAdapter",
                            "status": "✓ completed" if found else "~ partial (0 sources)",
                            "sources_found": len(found)})
        except Exception as e:
            log.warning("IRPageAdapter failed: %s", e)
            s1b_sub.append({"adapter": "IRPageAdapter", "status": "✗ failed", "reason": str(e)})
    else:
        s1b_sub.append({"adapter": "IRPageAdapter", "status": "– skipped", "reason": "disabled in profile"})

    if profile.get("enable_product_pages", False):
        product_adapter = ProductPageAdapter(
            cache=cache, max_pages=profile.get("max_product_pages", 2)
        )
        try:
            found = product_adapter.search(company, cutoff=as_of)
            ext_sources.extend(found)
            log.info("ProductPageAdapter: %d pages for %s", len(found), company.symbol)
            s1b_sub.append({"adapter": "ProductPageAdapter",
                            "status": "✓ completed" if found else "~ partial (0 sources)",
                            "sources_found": len(found)})
        except Exception as e:
            log.warning("ProductPageAdapter failed: %s", e)
            s1b_sub.append({"adapter": "ProductPageAdapter", "status": "✗ failed", "reason": str(e)})
    else:
        s1b_sub.append({"adapter": "ProductPageAdapter", "status": "– skipped", "reason": "disabled in profile"})

    if profile.get("enable_web_search", False):
        web_adapter = WebSearchAdapter(
            cache=cache,
            max_results=profile.get("web_search_results_per_query", 3),
        )
        try:
            found = web_adapter.search(company, cutoff=as_of)
            ext_sources.extend(found)
            log.info("WebSearchAdapter: %d URLs for %s", len(found), company.symbol)
            s1b_sub.append({"adapter": "WebSearchAdapter",
                            "status": "✓ completed" if found else "~ partial (0 sources)",
                            "sources_found": len(found)})
        except Exception as e:
            log.warning("WebSearchAdapter failed: %s", e)
            s1b_sub.append({"adapter": "WebSearchAdapter", "status": "✗ failed", "reason": str(e)})
    else:
        s1b_sub.append({"adapter": "WebSearchAdapter", "status": "– skipped", "reason": "disabled in profile"})

    for src in ext_sources:
        db.upsert_source(src, run.run_id)
    log.info("External sources total: %d", len(ext_sources))

    s1b.finish(
        status="completed" if ext_sources else "partial",
        total_external_sources=len(ext_sources),
        adapters=s1b_sub,
    )

    # Step 1c: Peer selection and peer EDGAR acquisition
    peer_identities: list[CompanyIdentity] = []
    if profile.get("enable_peer_search", True):
        log.info("Step 1c/12 — Peer selection (max_peers=%d)", profile.get("max_competitors", 5))
        s1c = flow.begin("1c", "Peer Selection")
        peer_selector = PeerSelector(
            cache=cache,
            max_peers=profile.get("max_competitors", 5),
            max_peer_filings=profile.get("max_peer_filings", 3),
        )
        peer_filings_added = 0
        try:
            peer_results = peer_selector.select(company, cutoff=as_of)
            for peer_identity, peer_sources in peer_results:
                peer_identities.append(peer_identity)
                db.upsert_company(peer_identity)
                for ps in peer_sources:
                    tagged = ps.model_copy(update={"is_peer": True})
                    db.upsert_source(tagged, run.run_id)
                    ext_sources.append(tagged)
                peer_filings_added += len(peer_sources)
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
            s1c.finish(
                status="completed" if peer_identities else "partial",
                peers_resolved=len(peer_identities),
                peers=[p.symbol for p in peer_identities],
                peer_filings_added=peer_filings_added,
            )
        except Exception as e:
            log.warning("Peer selection failed: %s", e)
            s1c.finish(status="failed", peers_resolved=0, error=str(e))
    else:
        log.info("Step 1c/12 — Peer selection skipped (disabled in profile)")
        flow.skip("1c", "Peer Selection", "disabled in profile")

    # Step 2: EDGAR source acquisition
    log.info("Step 2/12 — Source acquisition (max_filings=%d)", profile.get("max_filings", 20))
    s2 = flow.begin("2", "EDGAR Source Acquisition")
    edgar = EdgarAdapter(cache=cache, max_filings=profile.get("max_filings", 20))
    sources = edgar.search(company, cutoff=as_of)
    log.info("Found %d EDGAR sources after priority sort", len(sources))
    for i, src in enumerate(sources, 1):
        log.debug("  Source %02d: [%s] %s", i, src.source_type, src.title)
    for source in sources:
        db.upsert_source(source, run.run_id)
    from collections import Counter
    form_counts = dict(Counter(s.source_type for s in sources))
    s2.finish(sources_found=len(sources), form_types=form_counts)

    # Merge external + EDGAR sources for fetch/parse/index
    sources = ext_sources + sources

    # Shared HTML adapter for fetching external (non-EDGAR) sources
    _html_adapter = WebSearchAdapter(cache=cache, max_results=0)

    # Step 3+4: Fetch, parse, index
    log.info("Step 3+4/12 — Fetch, parse, and vector-index %d sources", len(sources))
    s34 = flow.begin("3-4", "Fetch / Parse / Index")
    indexed, skipped = 0, 0
    fetch_detail: list[dict] = []
    for source in sources:
        log.info("Fetching [%s] %s", source.source_type, source.title)
        try:
            _adapter = edgar if source.reliability_tier == 1 else _html_adapter
            raw_doc = _adapter.fetch(source)
            is_new = db.upsert_document(raw_doc)
            cache_tag = "new" if is_new else "cached"
            log.debug("Document %s (%s, %d bytes)", source.source_id, cache_tag, raw_doc.size_bytes)
            norm_doc = _adapter.normalize(raw_doc)
            target_vs = peer_vector_store if source.is_peer else vector_store
            # Index when: doc is new to the DB, VectorStore was just cleared, or
            # doc is already in the DB but somehow missing from the VectorStore
            # (happens when the VectorStore was rebuilt after a prior run indexed the doc).
            needs_index = is_new or target_vs.was_reset or not target_vs.has_document(norm_doc.doc_id)
            if needs_index:
                n_chunks = target_vs.index_document(
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
                collection = "peers" if source.is_peer else "own"
                log.info("Indexed %d chunks from %s into %s collection", n_chunks, source.source_type, collection)
            else:
                n_chunks = 0
                log.info("Skipped indexing %s — content unchanged, already in VectorStore", source.title[:60])
            fetch_detail.append({"title": source.title, "type": source.source_type, "chunks": n_chunks, "cache": cache_tag})
            indexed += 1
        except Exception as e:
            log.error("Failed to fetch/parse/index %s: %s", source.url, e)
            fetch_detail.append({"title": source.title, "type": source.source_type, "status": "✗ failed", "error": str(e)})
            skipped += 1

    log.info(
        "Indexing complete: %d indexed, %d skipped — own=%d chunks, peers=%d chunks",
        indexed, skipped, vector_store.count, peer_vector_store.count,
    )
    s34.finish(
        status="completed" if skipped == 0 else "partial",
        indexed=indexed,
        skipped=skipped,
        own_chunks=vector_store.count,
        peer_chunks=peer_vector_store.count,
        sources=fetch_detail,
    )

    return _run_analysis(
        symbol=symbol,
        as_of=as_of,
        lookback_years=lookback_years,
        out_dir=out_dir,
        profile=profile,
        dry_run=dry_run,
        effective_rag_top_k=effective_rag_top_k,
        company=company,
        run=run,
        db=db,
        cache=cache,
        vector_store=vector_store,
        llm=llm,
        flow=flow,
    )


def _run_analysis(
    *,
    symbol: str,
    as_of: date,
    lookback_years: int,
    out_dir: Path,
    profile: dict,
    dry_run: bool,
    effective_rag_top_k: int,
    company: Any,
    run: ResearchRun,
    db: Any,
    cache: Any,
    vector_store: Any,
    llm: Any,
    flow: Any,
) -> ResearchRun:
    """Steps 5–12: fact extraction → analysis → report → QA → export.

    Called from both _run() (full pipeline) and report_only() (RAG-only).
    """
    # Step 5: XBRL metrics
    log.info("Step 5/12 — XBRL financial metric extraction")
    s5 = flow.begin("5", "XBRL Metric Extraction")
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
        s5.finish(metrics_stored=len(metrics))
    except Exception as e:
        log.warning("XBRL extraction failed: %s", e)
        s5.finish(status="failed", error=str(e))

    # Step 6: RAG fact extraction
    target_sections = profile.get("sections", ["company_snapshot"])
    if isinstance(target_sections, str) and target_sections == "all":
        target_sections = list(SECTION_TOPICS.keys())

    log.info(
        "Step 6/12 — RAG fact extraction | sections=%d | rag_top_k=%d",
        len(target_sections), effective_rag_top_k,
    )
    s6 = flow.begin("6", "RAG Fact Extraction")
    all_facts: list[EvidenceFact] = []
    section_facts: dict[str, int] = {}
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
            section_facts[section] = len(facts)
            log.debug("Section '%s' → %d facts (running total=%d)", section, len(facts), len(all_facts))
        except Exception as e:
            log.error("Fact extraction failed for section '%s': %s", section, e)
            section_facts[section] = 0
            s6.warn(f"section '{section}' failed: {e}")

    log.info("Fact extraction complete: %d facts across %d sections", len(all_facts), len(target_sections))
    s6.finish(
        status="completed" if dry_run else ("completed" if all_facts else "partial"),
        facts_extracted=len(all_facts),
        dry_run_prompts_saved=len(target_sections) if dry_run else 0,
        sections=section_facts,
    )

    # Step 7: Contradiction detection
    contradictions: list = []
    log.info("Step 7/12 — Contradiction detection (%d facts)", len(all_facts))
    if all_facts:
        s7 = flow.begin("7", "Contradiction Detection")
        try:
            contradictions = llm.detect_counterevidence(all_facts, run.run_id)
            for c in contradictions:
                db.insert_contradiction(c)
            log.info("Detected %d contradictions", len(contradictions))
            s7.finish(contradictions_found=len(contradictions))
        except Exception as e:
            log.error("Contradiction detection failed: %s", e)
            s7.finish(status="failed", error=str(e))
    else:
        log.warning("No facts available — skipping contradiction detection")
        flow.skip("7", "Contradiction Detection", "no facts extracted")

    # Step 8: Citation verification
    log.info("Step 8/12 — Citation verification")
    s8 = flow.begin("8", "Citation Verification")
    try:
        verified, failed_cit = verify_citations(run.run_id, db, cache)
        log.info("Citations: %d verified, %d failed", verified, failed_cit)
        s8.finish(verified=verified, failed=failed_cit)
    except Exception as e:
        log.error("Citation verification failed: %s", e)
        s8.finish(status="failed", error=str(e))

    # Step 9: Section analysis
    log.info("Step 9/12 — Section analysis (%d sections)", len(target_sections))
    s9 = flow.begin("9", "Section Analysis")
    analyze_all_sections(
        sections=target_sections,
        facts=all_facts,
        run=run,
        db=db,
        llm=llm,
    )
    s9.finish(sections_analyzed=len(target_sections))

    # Step 10: Report generation
    log.info("Step 10/12 — Report generation")
    s10 = flow.begin("10", "Report Generation")
    try:
        report_md = generate_report(run=run, company=company, db=db, llm=llm)
        # Use all sources for the symbol (not just this run_id) so report_only runs
        # can resolve citations from 10-Ks indexed in a previous analyze run.
        db_sources = db.get_sources_for_symbol(symbol)
        conclusion_dicts = db.get_conclusions(run.run_id)
        contradiction_dicts = [c.model_dump() if hasattr(c, "model_dump") else dict(c) for c in contradictions]
        write_report(
            report_md=report_md,
            sources=db_sources,
            out_dir=out_dir,
            contradictions=contradiction_dicts,
            conclusions=conclusion_dicts,
        )
        report_path = out_dir / "report.md"
        word_count = len(report_md.split())
        log.info(
            "Report written: %s (%d chars, %d words)",
            report_path, len(report_md), word_count,
        )
        s10.finish(word_count=word_count, char_count=len(report_md))
    except Exception as e:
        log.error("Report generation failed: %s", e)
        s10.finish(status="failed", error=str(e))

    # Step 11: QA
    log.info("Step 11/12 — QA checks")
    s11 = flow.begin("11", "QA Checks")
    qa_result = run_qa(run.run_id, db, out_dir=out_dir)
    for check, passed in qa_result.checks.items():
        level = logging.INFO if passed else logging.WARNING
        log.log(level, "  QA %-40s %s", check, "PASS" if passed else "FAIL")
    qa_summary = {k: ("PASS" if v else "FAIL") for k, v in qa_result.checks.items()}
    s11.finish(
        status="completed" if qa_result.passed else "partial",
        passed=qa_result.passed,
        checks=qa_summary,
    )

    # Step 12: Export
    log.info("Step 12/12 — Export to %s", out_dir)
    s12 = flow.begin("12", "Export")
    export_run(run.run_id, db, out_dir, symbol=symbol)
    export_qa(qa_result, out_dir)
    monitoring = build_monitoring_dashboard(run.run_id, symbol.upper(), as_of, db)
    export_monitoring(monitoring, out_dir)

    status = "completed" if qa_result.passed else "partial"
    db.update_run_status(run.run_id, status, datetime.utcnow().isoformat())
    run.status = status
    run.completed_at = datetime.utcnow()

    flow.finish_run(status)
    export_flow(flow, out_dir)

    files_written = [
        "sources.json", "evidence.jsonl", "metrics.csv", "contradictions.json",
        "open_questions.json", "conclusions.json", "company_profile.json",
        "peers.json", "qa_report.json", "run_flow.json", "monitoring.json",
    ]
    s12.finish(files_written=files_written)

    if qa_result.passed:
        log.info("=== Run COMPLETED (run_id=%s) ===", run.run_id)
    else:
        log.warning(
            "=== Run PARTIAL (run_id=%s) — QA failures: %s ===",
            run.run_id, "; ".join(qa_result.critical_failures),
        )

    return run


def report_only(
    symbol: str,
    depth: str,
    as_of: date,
    lookback_years: int,
    output_root: Path,
    dry_run: bool = False,
    rag_top_k: int | None = None,
) -> ResearchRun:
    """Generate a report from the existing RAG — skip all source fetching and indexing.

    Uses whatever documents are already in the VectorStore for `symbol` and runs
    Steps 5-12 (XBRL → fact extraction → analysis → report → QA → export) on a
    fresh run record. The output directory is the same as a normal analyze() run
    so HTML conversion and the serve command work unchanged.
    """
    profile = settings.profile(depth)
    out_dir = output_root / symbol.upper() / as_of.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)

    file_handler = _attach_file_log(out_dir / "run.log")
    try:
        effective_rag_top_k = rag_top_k if rag_top_k is not None else profile.get("rag_top_k", 12)
        chunk_size = profile.get("chunk_size", 2800)
        chunk_overlap = profile.get("chunk_overlap", 350)

        db = Database(output_root / "research.db")
        cache = RawCache(output_root / ".cache")
        vector_store = VectorStore(
            base_dir=output_root, symbol=symbol,
            chunk_size=chunk_size, chunk_overlap=chunk_overlap,
        )

        if dry_run:
            from company_research.llm.dry_run import DryRunProvider
            llm = DryRunProvider(prompts_dir=out_dir / "prompts")
        else:
            llm = AnthropicProvider(log_dir=out_dir)

        _log_run_header(
            symbol=symbol, depth=depth, as_of=as_of,
            lookback_years=lookback_years, model_id=settings.model_id,
            dry_run=dry_run, rag_top_k=effective_rag_top_k, out_dir=out_dir,
        )
        log.info("report-only mode: skipping source fetch/index, RAG has %d chunks", vector_store.count)

        company = resolve(symbol)
        db.upsert_company(company)

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

        flow = RunFlowRecorder(
            run_id=run.run_id,
            symbol=symbol.upper(),
            depth=depth,
            as_of_date=as_of.isoformat(),
            dry_run=dry_run,
            model_id=settings.model_id,
        )
        flow.skip("1b", "External Source Discovery", "report-only mode")
        flow.skip("1c", "Peer Selection", "report-only mode")
        flow.skip("2", "EDGAR Source Acquisition", "report-only mode")
        flow.skip("3-4", "Fetch / Parse / Index", "report-only mode")

        return _run_analysis(
            symbol=symbol,
            as_of=as_of,
            lookback_years=lookback_years,
            out_dir=out_dir,
            profile=profile,
            dry_run=dry_run,
            effective_rag_top_k=effective_rag_top_k,
            company=company,
            run=run,
            db=db,
            cache=cache,
            vector_store=vector_store,
            llm=llm,
            flow=flow,
        )
    finally:
        _detach_file_log(file_handler)


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
