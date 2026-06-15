from __future__ import annotations

import io
import re

from pdfminer.high_level import extract_pages
from pdfminer.layout import LAParams, LTAnno, LTChar, LTTextContainer

from company_research.models.sources import (
    DocumentSection,
    NormalizedDocument,
    RawDocument,
)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_pdf(document: RawDocument, raw_bytes: bytes) -> NormalizedDocument:
    pages_text: list[str] = []
    laparams = LAParams(line_margin=0.5)

    for page_layout in extract_pages(io.BytesIO(raw_bytes), laparams=laparams):
        page_parts: list[str] = []
        for element in page_layout:
            if isinstance(element, LTTextContainer):
                page_parts.append(element.get_text())
        pages_text.append("".join(page_parts))

    # Build full text with page markers for offset tracking
    full_parts: list[str] = []
    page_offsets: list[tuple[int, int]] = []  # (page_num, char_offset)
    char_offset = 0

    for page_num, page_text in enumerate(pages_text, start=1):
        cleaned = _clean(page_text)
        if cleaned:
            page_offsets.append((page_num, char_offset))
            full_parts.append(cleaned)
            char_offset += len(cleaned) + 1

    full_text = " ".join(full_parts)

    # Build simple page-based sections
    sections: list[DocumentSection] = []
    for page_num, offset in page_offsets:
        page_text_clean = _clean(pages_text[page_num - 1])
        if page_text_clean:
            sections.append(
                DocumentSection(
                    heading=f"Page {page_num}",
                    text=page_text_clean,
                    char_offset=offset,
                )
            )

    return NormalizedDocument(
        doc_id=document.doc_id,
        source_id=document.source_id,
        text=full_text,
        sections=sections,
        tables=[],  # PDF table extraction deferred to M2
        metadata={
            "page_count": len(pages_text),
            "page_offsets": [{"page": p, "offset": o} for p, o in page_offsets],
            "parser": "pdf",
        },
    )
