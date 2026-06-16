"""Unit tests for M4 diff and monitoring models + helpers."""
from __future__ import annotations

from datetime import date

import pytest

from company_research.models.diff import (
    ConclusionChange,
    FactChange,
    MetricChange,
    MonitoringDashboard,
    MonitoringIndicator,
    ResearchDiff,
)
from company_research.pipeline_update import (
    _diff_conclusions,
    _diff_facts,
    _diff_metrics,
)


# ── ResearchDiff model ────────────────────────────────────────────────────────


class TestResearchDiffModel:
    def test_default_fields(self):
        d = ResearchDiff(
            symbol="AAPL",
            prior_run_id="a",
            new_run_id="b",
            prior_date=date(2025, 6, 15),
            new_date=date(2026, 6, 15),
        )
        assert d.symbol == "AAPL"
        assert d.new_sources_count == 0
        assert d.new_facts == []
        assert d.changed_metrics == []
        assert d.changed_conclusions == []
        assert d.diff_id  # uuid generated

    def test_serialization_roundtrip(self):
        d = ResearchDiff(
            symbol="MSFT",
            prior_run_id="x",
            new_run_id="y",
            prior_date=date(2025, 1, 1),
            new_date=date(2026, 1, 1),
            new_sources_count=5,
        )
        raw = d.model_dump_json()
        d2 = ResearchDiff.model_validate_json(raw)
        assert d2.symbol == "MSFT"
        assert d2.new_sources_count == 5


# ── MetricChange ─────────────────────────────────────────────────────────────


class TestMetricChange:
    def test_basic(self):
        m = MetricChange(
            name="Revenues", period="2025-09-30", unit="USD",
            prior_value=100.0, new_value=120.0, change_pct=20.0,
        )
        assert m.change_pct == 20.0

    def test_new_metric_no_prior(self):
        m = MetricChange(name="GrossProfit", period="2026-01-01", unit="USD", new_value=50.0)
        assert m.prior_value is None
        assert m.change_pct is None


# ── _diff_metrics ────────────────────────────────────────────────────────────


class TestDiffMetrics:
    def _m(self, name, period, value, period_type="annual"):
        return {"name": name, "period": period, "value": value, "unit": "USD", "period_type": period_type}

    def test_no_change(self):
        prior = [self._m("Revenue", "2025", 100.0)]
        new = [self._m("Revenue", "2025", 100.0)]
        changes = _diff_metrics(prior, new)
        assert changes == []

    def test_value_changed(self):
        prior = [self._m("Revenue", "2025", 100.0)]
        new = [self._m("Revenue", "2025", 120.0)]
        changes = _diff_metrics(prior, new)
        assert len(changes) == 1
        assert changes[0].change_pct == pytest.approx(20.0)

    def test_new_metric_appears(self):
        prior: list[dict] = []
        new = [self._m("GrossProfit", "2026", 50.0)]
        changes = _diff_metrics(prior, new)
        assert len(changes) == 1
        assert changes[0].prior_value is None
        assert changes[0].new_value == 50.0

    def test_multiple_periods(self):
        prior = [self._m("Revenue", "2024", 90.0), self._m("Revenue", "2025", 100.0)]
        new = [self._m("Revenue", "2024", 90.0), self._m("Revenue", "2025", 105.0), self._m("Revenue", "2026", 110.0)]
        changes = _diff_metrics(prior, new)
        names_periods = {(c.name, c.period) for c in changes}
        assert ("Revenue", "2025") in names_periods
        assert ("Revenue", "2026") in names_periods
        assert ("Revenue", "2024") not in names_periods

    def test_zero_prior_change_pct_is_none(self):
        prior = [self._m("X", "2025", 0.0)]
        new = [self._m("X", "2025", 10.0)]
        changes = _diff_metrics(prior, new)
        assert len(changes) == 1
        assert changes[0].change_pct is None  # can't compute % change from zero


# ── _diff_facts ──────────────────────────────────────────────────────────────


class TestDiffFacts:
    def _f(self, topic, claim, source_id="s1"):
        return {"topic": topic, "claim": claim, "source_id": source_id}

    def test_no_new_facts(self):
        prior = [self._f("revenue_model", "Earns via subscriptions")]
        new = [self._f("revenue_model", "Earns via subscriptions")]
        changes = _diff_facts(prior, new)
        assert changes == []

    def test_new_fact_detected(self):
        prior = [self._f("revenue_model", "Earns via subscriptions")]
        new = [
            self._f("revenue_model", "Earns via subscriptions"),
            self._f("revenue_model", "Also earns via hardware sales"),
        ]
        changes = _diff_facts(prior, new)
        assert len(changes) == 1
        assert changes[0].change_type == "new"
        assert "hardware" in changes[0].new_claim

    def test_entirely_new_topic(self):
        prior = [self._f("revenue_model", "Earns via subscriptions")]
        new = [
            self._f("revenue_model", "Earns via subscriptions"),
            self._f("key_risks", "Tariff exposure in Asia"),
        ]
        changes = _diff_facts(prior, new)
        assert any(c.topic == "key_risks" for c in changes)

    def test_empty_prior(self):
        new = [self._f("company_snapshot", "Apple makes iPhones")]
        changes = _diff_facts([], new)
        assert len(changes) == 1


# ── _diff_conclusions ────────────────────────────────────────────────────────


class TestDiffConclusions:
    def _c(self, section, conclusion, confidence="medium"):
        return {"section": section, "conclusion": conclusion, "confidence": confidence}

    def test_same_conclusion(self):
        prior = [self._c("revenue_model", "Subscription model is durable")]
        new = [self._c("revenue_model", "Subscription model is durable")]
        changes = _diff_conclusions(prior, new)
        assert len(changes) == 1
        assert changes[0].change_type == "same"

    def test_changed_conclusion(self):
        prior = [self._c("revenue_model", "Subscription model is durable", "high")]
        new = [self._c("revenue_model", "Pricing pressure may reduce durability", "medium")]
        changes = _diff_conclusions(prior, new)
        assert len(changes) == 1
        assert changes[0].change_type == "changed"
        assert changes[0].prior_confidence == "high"
        assert changes[0].new_confidence == "medium"

    def test_new_section(self):
        prior: list[dict] = []
        new = [self._c("key_risks", "Supply chain exposure to TSMC")]
        changes = _diff_conclusions(prior, new)
        assert len(changes) == 1
        assert changes[0].change_type == "new"

    def test_multiple_sections(self):
        prior = [self._c("revenue_model", "Stable"), self._c("competitive_advantage", "Strong moat")]
        new = [
            self._c("revenue_model", "Stable"),
            self._c("competitive_advantage", "Moat weakening due to AI"),
            self._c("key_risks", "New risk identified"),
        ]
        changes = _diff_conclusions(prior, new)
        by_section = {c.section: c for c in changes}
        assert by_section["revenue_model"].change_type == "same"
        assert by_section["competitive_advantage"].change_type == "changed"
        assert by_section["key_risks"].change_type == "new"


# ── MonitoringDashboard ──────────────────────────────────────────────────────


class TestMonitoringDashboard:
    def test_empty(self):
        dash = MonitoringDashboard(
            symbol="AAPL",
            as_of_date=date(2026, 6, 15),
            run_id="run-1",
        )
        assert dash.indicators == []

    def test_with_indicators(self):
        ind = MonitoringIndicator(
            section="revenue_model",
            indicator="Net revenue retention",
            run_id="run-1",
            symbol="AAPL",
            as_of_date=date(2026, 6, 15),
        )
        dash = MonitoringDashboard(
            symbol="AAPL",
            as_of_date=date(2026, 6, 15),
            run_id="run-1",
            indicators=[ind],
        )
        assert len(dash.indicators) == 1
        assert dash.indicators[0].section == "revenue_model"

    def test_serialization(self):
        dash = MonitoringDashboard(
            symbol="NVDA",
            as_of_date=date(2026, 6, 15),
            run_id="run-2",
        )
        raw = dash.model_dump_json()
        d2 = MonitoringDashboard.model_validate_json(raw)
        assert d2.symbol == "NVDA"
