from __future__ import annotations

import re

from company_research.models.sources import DocumentSection, NormalizedDocument, RawDocument


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_text(document: RawDocument, raw_bytes: bytes) -> NormalizedDocument:
    text = raw_bytes.decode("utf-8", errors="replace")
    full_text = _clean(text)
    return NormalizedDocument(
        doc_id=document.doc_id,
        source_id=document.source_id,
        text=full_text,
        sections=[DocumentSection(heading="Full text", text=full_text, char_offset=0)],
        tables=[],
        metadata={"parser": "text"},
    )
