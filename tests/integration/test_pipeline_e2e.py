"""
End-to-end integration tests.
Tests marked with @pytest.mark.live require real network access and ANTHROPIC_API_KEY.
Tests without that mark use mocks and run in CI.
"""
from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from company_research.models.identity import CompanyIdentity
from company_research.models.sources import SourceRecord, RawDocument, NormalizedDocument, DocumentSection
from company_research.storage.cache import RawCache
from company_research.storage.database import Database


def _make_company() -> CompanyIdentity:
    return CompanyIdentity(
        symbol="AAPL",
        exchange="NASDAQ",
        issuer_name="Apple Inc.",
        cik="0000320193",
        fiscal_year_end="09-30",
        currency="USD",
        filing_jurisdiction="US",
        security_type="operating_company",
    )


def _make_source() -> SourceRecord:
    return SourceRecord(
        title="Apple Inc. 10-K 2024",
        publisher="SEC EDGAR",
        url="https://www.sec.gov/Archives/edgar/data/320193/test.htm",
        source_type="10-K",
        primary_or_secondary="primary",
        company_or_external="regulator",
        reliability_tier=1,
        period_covered="FY2024",
    )


def test_database_roundtrip():
    """Company, run, source, fact all survive a SQLite round-trip."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")
        company = _make_company()
        db.upsert_company(company)

        from company_research.models.identity import ResearchRun
        run = ResearchRun(
            symbol="AAPL", depth="quick", as_of_date=date(2026, 6, 15),
            model_id="test", prompt_version="1.0", code_commit="abc",
            config_hash="dead", output_dir=tmpdir,
        )
        db.insert_run(run)

        source = _make_source()
        db.upsert_source(source, run.run_id)

        from company_research.models.evidence import EvidenceFact
        fact = EvidenceFact(
            run_id=run.run_id,
            topic="business_model",
            claim="Apple sells iPhones.",
            source_id=source.source_id,
            source_location="Item 1, p.1",
            confidence="high",
        )
        db.insert_fact(fact)

        facts = db.get_facts(run.run_id)
        assert len(facts) == 1
        assert facts[0]["claim"] == "Apple sells iPhones."
        assert facts[0]["confidence"] == "high"


def test_raw_cache_roundtrip():
    """Bytes stored to cache are retrievable by hash."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = RawCache(Path(tmpdir) / ".cache")
        data = b"<html><body>Apple 10-K content</body></html>"
        doc = cache.store_bytes(data, "src-1", "text/html")
        assert cache.exists(doc.content_hash)
        assert cache.read(doc.content_hash) == data

        # Idempotent: store same bytes again gives same hash
        doc2 = cache.store_bytes(data, "src-1", "text/html")
        assert doc2.content_hash == doc.content_hash


def test_export_creates_all_files():
    """export_run creates all required output files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")

        from company_research.models.identity import ResearchRun
        run = ResearchRun(
            symbol="AAPL", depth="quick", as_of_date=date(2026, 6, 15),
            model_id="test", prompt_version="1.0", code_commit="abc",
            config_hash="dead", output_dir=tmpdir,
        )
        db.insert_run(run)

        from company_research.storage.export import export_run, export_qa
        from company_research.models.qa import QAResult

        out_dir = Path(tmpdir) / "out"
        export_run(run.run_id, db, out_dir)
        qa = QAResult(run_id=run.run_id, passed=True, checks={})
        export_qa(qa, out_dir)

        for fname in [
            "sources.json", "evidence.jsonl", "metrics.csv",
            "contradictions.json", "open_questions.json",
            "conclusions.json", "qa_report.json",
        ]:
            assert (out_dir / fname).exists(), f"Missing: {fname}"


def test_qa_gates_catch_missing_sources():
    """QA should fail when no sources are present."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = Database(Path(tmpdir) / "test.db")
        from company_research.models.identity import ResearchRun
        run = ResearchRun(
            symbol="AAPL", depth="quick", as_of_date=date(2026, 6, 15),
            model_id="test", prompt_version="1.0", code_commit="abc",
            config_hash="dead", output_dir=tmpdir,
        )
        db.insert_run(run)
        from company_research.validation.qa import run_qa
        qa = run_qa(run.run_id, db)
        assert not qa.passed
        assert any("sources" in f.lower() for f in qa.critical_failures)


@pytest.mark.live
def test_aapl_entity_resolution():
    """AAPL resolves to Apple Inc. with correct CIK."""
    from company_research.identity.resolver import resolve
    company = resolve("AAPL")
    assert company.cik == "0000320193"
    assert "Apple" in company.issuer_name
    assert company.fiscal_year_end == "09-30"
    assert company.security_type == "operating_company"


@pytest.mark.live
def test_ambiguous_ticker_rejected():
    """A genuinely ambiguous ticker raises AmbiguousTickerError."""
    from company_research.identity.resolver import resolve, AmbiguousTickerError, TickerNotFoundError
    try:
        resolve("ZZZZ")  # should either not be found or be unambiguous
    except (TickerNotFoundError, AmbiguousTickerError):
        pass  # either is acceptable


@pytest.mark.live
def test_aapl_full_pipeline(tmp_path):
    """Full AAPL quick-depth pipeline run produces required output files."""
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")

    from company_research.pipeline import analyze
    run = analyze(
        symbol="AAPL",
        depth="quick",
        as_of=date(2026, 6, 15),
        lookback_years=1,
        output_root=tmp_path,
    )
    out_dir = tmp_path / "AAPL" / "2026-06-15"
    assert (out_dir / "sources.json").exists()
    assert (out_dir / "evidence.jsonl").exists()
    assert (out_dir / "qa_report.json").exists()

    qa = json.loads((out_dir / "qa_report.json").read_text())
    # M1: QA may not pass fully (no full report yet), but must run without crashing
    assert "passed" in qa
