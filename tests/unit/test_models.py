from datetime import date, datetime

import pytest
from pydantic import ValidationError

from company_research.models.identity import CompanyIdentity, ResearchRun
from company_research.models.sources import RawDocument, SourceRecord, NormalizedDocument, DocumentSection
from company_research.models.evidence import EvidenceFact, MetricObservation
from company_research.models.analysis import Contradiction, SectionConclusion
from company_research.models.citations import Citation
from company_research.models.qa import OpenQuestion, QAResult


def test_company_identity_cik_padded():
    c = CompanyIdentity(
        symbol="aapl",
        exchange="NASDAQ",
        issuer_name="Apple Inc.",
        cik="320193",
        fiscal_year_end="09-30",
        currency="USD",
        filing_jurisdiction="US",
    )
    assert c.cik == "0000320193"
    assert c.symbol == "AAPL"


def test_company_identity_security_type_default():
    c = CompanyIdentity(
        symbol="AAPL", exchange="NASDAQ", issuer_name="Apple",
        cik="0000320193", fiscal_year_end="09-30",
        currency="USD", filing_jurisdiction="US",
    )
    assert c.security_type == "unknown"


def test_source_record_defaults():
    s = SourceRecord(
        title="Apple 10-K 2024",
        publisher="SEC EDGAR",
        url="https://www.sec.gov/Archives/edgar/data/320193/test.htm",
        source_type="10-K",
    )
    assert s.primary_or_secondary == "secondary"
    assert s.reliability_tier == 8
    assert s.source_id  # auto-generated UUID


def test_source_record_reliability_tier_bounds():
    with pytest.raises(ValidationError):
        SourceRecord(
            title="x", publisher="y", url="http://x.com",
            source_type="10-K", reliability_tier=9,
        )


def test_evidence_fact_defaults():
    f = EvidenceFact(
        run_id="run-1",
        topic="revenue",
        claim="Revenue was $100M",
        value="100",
        unit="USD_millions",
        period="FY2024",
        source_id="src-1",
        source_location="Item 1, p.4",
    )
    assert f.fact_id
    assert f.confidence == "medium"
    assert f.extraction_method == "llm"
    assert f.fact_claim_or_inference == "fact"


def test_metric_observation_types():
    m = MetricObservation(
        run_id="run-1",
        name="revenue",
        value=391_035.0,
        unit="USD_millions",
        period="FY2024",
        period_type="fiscal",
        value_type="reported",
        currency="USD",
        source_id="src-1",
    )
    assert m.value == pytest.approx(391_035.0)


def test_contradiction_defaults():
    c = Contradiction(
        run_id="run-1",
        fact_id_a="f1",
        fact_id_b="f2",
        description="Revenue conflict",
        severity="material",
    )
    assert not c.resolved
    assert c.resolution is None


def test_section_conclusion_defaults():
    sc = SectionConclusion(
        run_id="run-1",
        section="company_snapshot",
        conclusion="Apple sells consumer electronics.",
        confidence="high",
    )
    assert sc.supporting_fact_ids == []
    assert sc.open_questions == []


def test_qa_result_passed():
    qa = QAResult(
        run_id="run-1",
        passed=True,
        checks={"has_sources": True},
    )
    assert qa.passed
    assert qa.critical_failures == []


def test_research_run_fields():
    run = ResearchRun(
        symbol="AAPL",
        depth="standard",
        as_of_date=date(2026, 6, 15),
        model_id="claude-sonnet-4-6",
        prompt_version="1.0.0",
        code_commit="abc1234",
        config_hash="deadbeef",
        output_dir="/tmp/research",
    )
    assert run.status == "running"
    assert run.run_id
