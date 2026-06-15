from datetime import datetime

import pytest

from company_research.models.sources import RawDocument
from company_research.parsing.html import parse_html
from company_research.parsing.text import parse_text


def _make_doc(mime_type: str = "text/html") -> RawDocument:
    return RawDocument(
        source_id="src-1",
        content_hash="abc123",
        file_path="/tmp/test",
        mime_type=mime_type,
        size_bytes=100,
        retrieved_at=datetime.utcnow(),
    )


def test_html_parser_extracts_text():
    html = b"<html><body><h1>Revenue</h1><p>Revenue was $100M in FY2024.</p></body></html>"
    doc = _make_doc()
    result = parse_html(doc, html)
    assert "Revenue was $100M in FY2024" in result.text
    assert result.doc_id == doc.doc_id
    assert result.source_id == "src-1"


def test_html_parser_extracts_sections():
    html = b"""
    <html><body>
      <h1>Business Overview</h1>
      <p>Apple designs consumer electronics.</p>
      <h2>Products</h2>
      <p>The iPhone is the primary product.</p>
    </body></html>
    """
    doc = _make_doc()
    result = parse_html(doc, html)
    headings = [s.heading for s in result.sections]
    assert any("Business" in h for h in headings)


def test_html_parser_extracts_tables():
    html = b"""
    <html><body>
      <table>
        <tr><th>Year</th><th>Revenue</th></tr>
        <tr><td>2024</td><td>$391B</td></tr>
        <tr><td>2023</td><td>$383B</td></tr>
      </table>
    </body></html>
    """
    doc = _make_doc()
    result = parse_html(doc, html)
    assert len(result.tables) == 1
    assert result.tables[0].headers == ["Year", "Revenue"]
    assert result.tables[0].rows[0] == ["2024", "$391B"]


def test_html_parser_strips_scripts():
    html = b"<html><body><script>alert('x')</script><p>Clean text.</p></body></html>"
    doc = _make_doc()
    result = parse_html(doc, html)
    assert "alert" not in result.text
    assert "Clean text" in result.text


def test_text_parser():
    raw = b"  Apple  Inc.  sells  iPhones.  "
    doc = _make_doc("text/plain")
    result = parse_text(doc, raw)
    assert result.text == "Apple Inc. sells iPhones."
    assert len(result.sections) == 1
