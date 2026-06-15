"""Unit tests for the report.md → HTML converter."""
from __future__ import annotations

import pytest

from company_research.reporting.html_export import (
    _inline_md,
    _parse_header,
    parse_report,
    render_html,
)

_SAMPLE = """\
# Test Corp (TST) — Product and Business Fundamentals

**As of:** 2025-01-01
**Research depth:** quick
**Primary listing:** NYSE
**Reporting currency:** USD

---

## 1. Executive Summary

This is the executive summary [abc12345-0000-0000-0000-000000000000].

Second paragraph here.

---

**Conclusion:** The company looks solid.

**Confidence:** Medium

**Counterevidence:** Evidence is limited [abc12345-0000-0000-0000-000000000000].

**What would change this conclusion:** More granular data would help.

---

## 2. Business Model

The company sells **widgets** to enterprise customers.

---

**Conclusion:** Revenue model is straightforward.

**Confidence:** High

**Counterevidence:** No segment data disclosed.

**What would change this conclusion:** Segment revenue breakdown.

---

*This report was generated automatically.*
"""


# ── header parsing ─────────────────────────────────────────────────────────────


def test_parse_header_company_and_ticker():
    company, ticker, subtitle, meta = _parse_header(
        "# Acme Inc. (ACME) — Product Fundamentals\n**As of:** 2025-01-01\n"
    )
    assert company == "Acme Inc."
    assert ticker == "ACME"
    assert subtitle == "Product Fundamentals"
    assert meta["As of"] == "2025-01-01"


def test_parse_header_no_subtitle():
    company, ticker, subtitle, meta = _parse_header("# Acme Inc. (ACME)\n")
    assert company == "Acme Inc."
    assert ticker == "ACME"
    assert subtitle == ""


def test_parse_header_metadata_keys():
    _, _, _, meta = _parse_header(
        "# Corp (C)\n**Research depth:** standard\n**Reporting currency:** USD\n"
    )
    assert meta["Research depth"] == "standard"
    assert meta["Reporting currency"] == "USD"


# ── section parsing ────────────────────────────────────────────────────────────


def test_parse_report_company_fields():
    data = parse_report(_SAMPLE)
    assert data.company == "Test Corp"
    assert data.ticker == "TST"
    assert data.subtitle == "Product and Business Fundamentals"


def test_parse_report_section_count():
    data = parse_report(_SAMPLE)
    assert len(data.sections) == 2


def test_parse_report_section_numbering():
    data = parse_report(_SAMPLE)
    assert data.sections[0].number == 1
    assert data.sections[1].number == 2


def test_parse_report_section_title():
    data = parse_report(_SAMPLE)
    assert data.sections[0].title == "Executive Summary"
    assert data.sections[1].title == "Business Model"


def test_parse_report_body_paragraphs():
    data = parse_report(_SAMPLE)
    assert len(data.sections[0].body_paragraphs) == 2
    assert "executive summary" in data.sections[0].body_paragraphs[0]
    assert "Second paragraph" in data.sections[0].body_paragraphs[1]


# ── conclusion parsing ─────────────────────────────────────────────────────────


def test_conclusion_text():
    data = parse_report(_SAMPLE)
    assert data.sections[0].conclusion == "The company looks solid."


def test_confidence_medium():
    data = parse_report(_SAMPLE)
    assert data.sections[0].confidence == "Medium"


def test_confidence_high():
    data = parse_report(_SAMPLE)
    assert data.sections[1].confidence == "High"


def test_counterevidence():
    data = parse_report(_SAMPLE)
    assert "Evidence is limited" in data.sections[0].counterevidence


def test_what_would_change():
    data = parse_report(_SAMPLE)
    assert "granular data" in data.sections[0].what_would_change


# ── footer ─────────────────────────────────────────────────────────────────────


def test_footer():
    data = parse_report(_SAMPLE)
    assert "generated automatically" in data.footer


# ── inline markdown ────────────────────────────────────────────────────────────


def test_inline_uuid_citation():
    uuid = "bf35558f-7c2f-451b-9793-5658660b96b9"
    out = _inline_md(f"Text [{uuid}].")
    assert 'class="cit"' in out
    assert "bf35558f" in out
    assert f'title="{uuid}"' in out


def test_inline_bold():
    out = _inline_md("This is **bold** here.")
    assert "<strong>bold</strong>" in out


def test_inline_html_escaping():
    out = _inline_md("A < B & C > D")
    assert "&lt;" in out
    assert "&amp;" in out
    assert "&gt;" in out


def test_inline_xss_prevention():
    out = _inline_md('<script>alert("xss")</script>')
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


# ── HTML rendering ─────────────────────────────────────────────────────────────


def test_render_html_doctype():
    data = parse_report(_SAMPLE)
    out = render_html(data)
    assert out.startswith("<!DOCTYPE html>")


def test_render_html_title():
    data = parse_report(_SAMPLE)
    out = render_html(data)
    assert "Test Corp (TST)" in out


def test_render_html_section_ids():
    data = parse_report(_SAMPLE)
    out = render_html(data)
    assert 'id="s1"' in out
    assert 'id="s2"' in out


def test_render_html_confidence_badge():
    data = parse_report(_SAMPLE)
    out = render_html(data)
    assert "conf-badge medium" in out
    assert "conf-badge high" in out


def test_render_html_toc_links():
    data = parse_report(_SAMPLE)
    out = render_html(data)
    assert 'href="#s1"' in out
    assert 'href="#s2"' in out


def test_render_html_no_raw_uuids_in_body():
    data = parse_report(_SAMPLE)
    out = render_html(data)
    # Raw bracket-UUID format should not appear verbatim; it should be wrapped in <cite>
    assert "[abc12345-0000-0000-0000-000000000000]" not in out
    assert 'class="cit"' in out
