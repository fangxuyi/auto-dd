"""Unit tests for M2/RAG components: guidance loader, formatter, section analyzer, vector store."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from company_research.extraction.guidance import get_section_guidance
from company_research.reporting.formatter import _extract_executive_summary, _resolve_citations


# --- guidance loader ---

def test_guidance_loader_returns_string_for_known_section():
    g = get_section_guidance("company_snapshot")
    assert isinstance(g, str)
    assert len(g) > 100  # substantial content expected


def test_guidance_loader_returns_empty_for_unknown_section():
    g = get_section_guidance("nonexistent_section_xyz")
    assert g == ""


def test_guidance_loader_covers_all_section_topics():
    from company_research.extraction.facts import SECTION_TOPICS
    # Every section should at least attempt a lookup without erroring
    for section in SECTION_TOPICS:
        result = get_section_guidance(section)
        assert isinstance(result, str)


# --- report formatter ---

_SAMPLE_REPORT = """\
# Acme Corp (ACME) — Product and Business Fundamentals

**As of:** 2026-06-15
**Research depth:** quick

## 1. Executive Summary

Acme makes widgets. [src:SRC-001]

## 2. Company and Business Model

Acme Corp sells widgets to enterprise customers. [src:SRC-002]

**Conclusion:** Stable business.
**Confidence:** Medium
"""

_SOURCES = [
    {
        "source_id": "SRC-001",
        "title": "Acme Corp 10-K FY2025",
        "published_date": "2025-11-01",
        "accessed_date": "2026-06-15",
    },
    {
        "source_id": "SRC-002",
        "title": "Acme Corp 10-Q Q3 2025",
        "published_date": "2025-08-15",
        "accessed_date": "2026-06-15",
    },
]


def test_resolve_citations_replaces_tags():
    source_map = {s["source_id"]: s for s in _SOURCES}
    result = _resolve_citations("See [src:SRC-001] for details.", source_map)
    assert "[src:" not in result
    assert "Acme Corp 10-K FY2025" in result


def test_resolve_citations_handles_unknown_source():
    result = _resolve_citations("See [src:UNKNOWN] here.", {})
    assert "[UNKNOWN]" in result
    assert "[src:" not in result


def test_extract_executive_summary_finds_section():
    summary = _extract_executive_summary(_SAMPLE_REPORT)
    assert "Executive Summary" in summary
    assert "Acme makes widgets" in summary
    # Should not include section 2
    assert "sells widgets" not in summary


def test_write_report_creates_files():
    from company_research.reporting.formatter import write_report
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir)
        write_report(_SAMPLE_REPORT, _SOURCES, out)
        assert (out / "report.md").exists()
        assert (out / "executive_summary.md").exists()
        assert "Acme Corp 10-K FY2025" in (out / "report.md").read_text()
        assert "Executive Summary" in (out / "executive_summary.md").read_text()


# --- edgar filing prioritization ---

def test_edgar_prioritizes_10k_before_form4():
    from company_research.sources.edgar import _FORM_PRIORITY
    assert _FORM_PRIORITY["10-K"] < _FORM_PRIORITY["Form4"]
    assert _FORM_PRIORITY["10-Q"] < _FORM_PRIORITY["Form4"]
    assert _FORM_PRIORITY["20-F"] < _FORM_PRIORITY["Form4"]


# --- section analyzer ---

def test_analyze_all_sections_skips_insufficient_facts():
    from datetime import date
    import tempfile
    from company_research.analysis.sections import analyze_all_sections
    from company_research.models.identity import ResearchRun
    from company_research.storage.database import Database

    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")
        run = ResearchRun(
            symbol="TEST",
            depth="quick",
            as_of_date=date(2026, 6, 15),
            model_id="test",
            prompt_version="1.0",
            code_commit="abc",
            config_hash="dead",
            output_dir=tmpdir,
        )
        db.insert_run(run)

        llm_mock = MagicMock()
        # No facts → all sections should become open questions, not conclusions
        conclusions = analyze_all_sections(
            sections=["company_snapshot"],
            facts=[],
            run=run,
            db=db,
            llm=llm_mock,
        )
        assert conclusions == []
        llm_mock.analyze_section.assert_not_called()
        # Should have recorded an open question
        questions = db.get_questions(run.run_id)
        assert len(questions) == 1


def test_export_creates_company_profile_and_peers():
    from datetime import date
    import tempfile
    from company_research.models.identity import ResearchRun, CompanyIdentity
    from company_research.storage.database import Database
    from company_research.storage.export import export_run

    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")
        company = CompanyIdentity(
            symbol="AAPL",
            exchange="NASDAQ",
            issuer_name="Apple Inc.",
            cik="0000320193",
            fiscal_year_end="09-30",
            currency="USD",
            filing_jurisdiction="US",
            security_type="operating_company",
        )
        db.upsert_company(company)

        run = ResearchRun(
            symbol="AAPL",
            depth="quick",
            as_of_date=date(2026, 6, 15),
            model_id="test",
            prompt_version="1.0",
            code_commit="abc",
            config_hash="dead",
            output_dir=tmpdir,
        )
        db.insert_run(run)

        out_dir = Path(tmpdir) / "out"
        export_run(run.run_id, db, out_dir)

        assert (out_dir / "company_profile.json").exists()
        assert (out_dir / "peers.json").exists()
        peers = json.loads((out_dir / "peers.json").read_text())
        assert peers == []


# --- vector store ---

def test_vectorstore_index_and_retrieve():
    from company_research.storage.vectorstore import VectorStore
    with tempfile.TemporaryDirectory() as tmpdir:
        vs = VectorStore(base_dir=Path(tmpdir), symbol="TEST")
        n = vs.index_document(
            doc_id="doc-001",
            text=(
                "Apple Inc. sells iPhones, iPads, Macs, and services. "
                "The iPhone is the primary revenue driver, accounting for over 50% of revenue. "
                "Services including the App Store, iCloud, and Apple Music are the fastest growing segment. "
                "Apple competes with Samsung, Google, and Microsoft across its product lines. "
            ) * 20,  # repeat to get multiple chunks
            metadata={
                "source_id": "SRC-001",
                "title": "Apple 10-K FY2025",
                "source_type": "10-K",
                "period_covered": "FY2025",
            },
        )
        assert n > 0
        assert vs.count > 0

        results = vs.retrieve("iPhone revenue product description", k=3)
        assert len(results) > 0
        assert all("text" in r and "metadata" in r and "score" in r for r in results)
        assert all(r["metadata"]["source_id"] == "SRC-001" for r in results)
        # Most relevant chunk should have a meaningful similarity score
        assert results[0]["score"] > 0.0


def test_vectorstore_empty_retrieve():
    from company_research.storage.vectorstore import VectorStore
    with tempfile.TemporaryDirectory() as tmpdir:
        vs = VectorStore(base_dir=Path(tmpdir), symbol="EMPTY")
        results = vs.retrieve("anything", k=5)
        assert results == []


def test_topic_queries_cover_all_section_topics():
    from company_research.extraction.facts import SECTION_TOPICS
    from company_research.extraction.topic_queries import TOPIC_QUERIES
    topics = set(SECTION_TOPICS.values())
    for topic in topics:
        assert topic in TOPIC_QUERIES, f"No query for topic: {topic}"


def test_extract_and_store_uses_vector_store():
    """extract_and_store retrieves chunks and calls llm.extract_facts with them."""
    from datetime import date
    from company_research.extraction.facts import extract_and_store
    from company_research.models.identity import ResearchRun, CompanyIdentity
    from company_research.storage.database import Database
    from company_research.storage.vectorstore import VectorStore

    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")
        vs = VectorStore(base_dir=Path(tmpdir), symbol="TEST")
        vs.index_document(
            doc_id="doc-001",
            text="Apple Inc. sells hardware and software products globally. " * 50,
            metadata={"source_id": "SRC-001", "title": "Apple 10-K", "source_type": "10-K", "period_covered": "FY2025"},
        )

        company = CompanyIdentity(
            symbol="TEST", exchange="NASDAQ", issuer_name="Test Corp",
            cik="0000000001", fiscal_year_end="12-31", currency="USD",
            filing_jurisdiction="US", security_type="operating_company",
        )
        run = ResearchRun(
            symbol="TEST", depth="quick", as_of_date=date(2026, 6, 15),
            model_id="test", prompt_version="1.0", code_commit="abc",
            config_hash="dead", output_dir=tmpdir,
        )
        db.insert_run(run)

        from company_research.models.evidence import EvidenceFact
        from company_research.models.sources import SourceRecord
        src = SourceRecord(
            title="Test 10-K", publisher="SEC", url="https://example.com/10k.htm",
            source_type="10-K", primary_or_secondary="primary",
            company_or_external="regulator", reliability_tier=1,
        )
        db.upsert_source(src, run.run_id)
        mock_fact = EvidenceFact(
            run_id=run.run_id, topic="business_model",
            claim="Apple sells hardware.", source_id=src.source_id,
            source_location="Item 1", confidence="high",
        )
        llm_mock = MagicMock()
        llm_mock.extract_facts.return_value = [mock_fact]

        facts = extract_and_store(
            vector_store=vs, context=company, run_id=run.run_id,
            db=db, llm=llm_mock, section="company_snapshot",
        )
        assert len(facts) == 1
        # LLM was called with chunks (list of dicts), not a NormalizedDocument
        call_args = llm_mock.extract_facts.call_args
        assert isinstance(call_args.kwargs["chunks"], list)
        assert all("text" in c for c in call_args.kwargs["chunks"])


def test_qa_checks_report_files():
    from datetime import date
    import tempfile
    from company_research.models.identity import ResearchRun
    from company_research.models.sources import SourceRecord
    from company_research.models.evidence import EvidenceFact
    from company_research.storage.database import Database
    from company_research.validation.qa import run_qa

    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")
        run = ResearchRun(
            symbol="TEST",
            depth="quick",
            as_of_date=date(2026, 6, 15),
            model_id="test",
            prompt_version="1.0",
            code_commit="abc",
            config_hash="dead",
            output_dir=tmpdir,
        )
        db.insert_run(run)

        # Add minimal passing data
        src = SourceRecord(
            title="Test 10-K",
            publisher="SEC",
            url="https://example.com/10k.htm",
            source_type="10-K",
            primary_or_secondary="primary",
            company_or_external="regulator",
            reliability_tier=1,
        )
        db.upsert_source(src, run.run_id)
        fact = EvidenceFact(
            run_id=run.run_id,
            topic="business_model",
            claim="Company sells widgets.",
            source_id=src.source_id,
            source_location="Item 1",
            confidence="high",
        )
        db.insert_fact(fact)

        out_dir = Path(tmpdir) / "out"
        out_dir.mkdir()

        # Without report.md → should fail
        qa = run_qa(run.run_id, db, out_dir=out_dir)
        assert not qa.checks.get("report_md_exists", True)

        # Write report files → should pass that check
        (out_dir / "report.md").write_text("# Report\n")
        (out_dir / "executive_summary.md").write_text("# Summary\n")
        qa2 = run_qa(run.run_id, db, out_dir=out_dir)
        assert qa2.checks.get("report_md_exists", False)
        assert qa2.checks.get("executive_summary_exists", False)


# --- DryRunProvider ---

def test_dry_run_provider_writes_extract_facts_prompt():
    from datetime import date
    from company_research.llm.dry_run import DryRunProvider
    from company_research.models.identity import CompanyIdentity

    with tempfile.TemporaryDirectory() as tmpdir:
        prompts_dir = Path(tmpdir) / "prompts"
        provider = DryRunProvider(prompts_dir=prompts_dir)
        company = CompanyIdentity(
            symbol="TEST", exchange="NASDAQ", issuer_name="Test Corp",
            cik="0000000001", fiscal_year_end="12-31", currency="USD",
            filing_jurisdiction="US", security_type="operating_company",
        )
        chunks = [{"text": "Test Corp sells widgets.", "metadata": {"source_id": "SRC-001", "title": "Test 10-K", "source_type": "10-K", "period_covered": "FY2025"}, "score": 0.9}]
        facts = provider.extract_facts(chunks=chunks, context=company, run_id="run-001", topic="business_model")
        assert facts == []
        files = list(prompts_dir.glob("*.txt"))
        assert len(files) == 1
        assert "extract_business_model" in files[0].name
        content = files[0].read_text()
        assert "Test Corp" in content


def test_dry_run_provider_writes_analyze_section_prompt():
    from datetime import date
    from company_research.llm.dry_run import DryRunProvider
    from company_research.models.identity import ResearchRun

    with tempfile.TemporaryDirectory() as tmpdir:
        prompts_dir = Path(tmpdir) / "prompts"
        provider = DryRunProvider(prompts_dir=prompts_dir)
        run = ResearchRun(
            symbol="TEST", depth="quick", as_of_date=date(2026, 6, 15),
            model_id="test", prompt_version="1.0", code_commit="abc",
            config_hash="dead", output_dir=tmpdir,
        )
        conclusion = provider.analyze_section(section="company_snapshot", facts=[], run=run)
        assert conclusion.section == "company_snapshot"
        assert "[dry-run" in conclusion.conclusion
        files = list(prompts_dir.glob("*.txt"))
        assert len(files) == 1
        assert "analyze_company_snapshot" in files[0].name


def test_dry_run_provider_synthesize_report_returns_placeholder():
    from datetime import date
    from company_research.llm.dry_run import DryRunProvider
    from company_research.models.identity import CompanyIdentity, ResearchRun

    with tempfile.TemporaryDirectory() as tmpdir:
        prompts_dir = Path(tmpdir) / "prompts"
        provider = DryRunProvider(prompts_dir=prompts_dir)
        company = CompanyIdentity(
            symbol="ACME", exchange="NYSE", issuer_name="Acme Corp",
            cik="0000000002", fiscal_year_end="12-31", currency="USD",
            filing_jurisdiction="US", security_type="operating_company",
        )
        run = ResearchRun(
            symbol="ACME", depth="quick", as_of_date=date(2026, 6, 15),
            model_id="test", prompt_version="1.0", code_commit="abc",
            config_hash="dead", output_dir=tmpdir,
        )
        result = provider.synthesize_report(conclusions=[], run=run, company=company)
        assert "Acme Corp" in result
        assert "[dry-run" in result
        files = list(prompts_dir.glob("*.txt"))
        assert len(files) == 1
        assert "synthesize_report" in files[0].name


def test_dry_run_provider_counter_increments():
    from datetime import date
    from company_research.llm.dry_run import DryRunProvider
    from company_research.models.identity import CompanyIdentity, ResearchRun

    with tempfile.TemporaryDirectory() as tmpdir:
        prompts_dir = Path(tmpdir) / "prompts"
        provider = DryRunProvider(prompts_dir=prompts_dir)
        company = CompanyIdentity(
            symbol="TEST", exchange="NASDAQ", issuer_name="Test Corp",
            cik="0000000001", fiscal_year_end="12-31", currency="USD",
            filing_jurisdiction="US", security_type="operating_company",
        )
        run = ResearchRun(
            symbol="TEST", depth="quick", as_of_date=date(2026, 6, 15),
            model_id="test", prompt_version="1.0", code_commit="abc",
            config_hash="dead", output_dir=tmpdir,
        )
        chunks = [{"text": "x", "metadata": {"source_id": "SRC-001", "title": "T", "source_type": "10-K", "period_covered": ""}, "score": 0.5}]
        provider.extract_facts(chunks=chunks, context=company, run_id="r", topic="business_model")
        provider.extract_facts(chunks=chunks, context=company, run_id="r", topic="product")
        provider.analyze_section(section="company_snapshot", facts=[], run=run)
        files = sorted(prompts_dir.glob("*.txt"))
        assert len(files) == 3
        assert files[0].name.startswith("01_")
        assert files[1].name.startswith("02_")
        assert files[2].name.startswith("03_")
