from __future__ import annotations

import logging

from company_research.models.citations import Citation
from company_research.storage.cache import RawCache
from company_research.storage.database import Database

log = logging.getLogger(__name__)


def _quote_in_text(quote: str, text: str) -> bool:
    """Check if a quote (or a 30-char substring) appears in the source text."""
    if not quote:
        return False
    # Allow partial match: 30-char window from the start of the quote
    needle = quote[:30].strip().lower()
    return needle in text.lower()


def verify_citations(
    run_id: str,
    db: Database,
    cache: RawCache,
) -> tuple[int, int]:
    """Verify all citations for a run. Returns (verified, failed) counts."""
    citations = db.get_citations(run_id)
    verified = 0
    failed = 0

    for row in citations:
        citation_id = row["citation_id"]
        quote = row.get("quote")
        source_id = row["source_id"]

        if not quote:
            db.update_citation_verified(citation_id, True)
            verified += 1
            continue

        # Look up the raw document for this source
        docs = db.get_document_by_hash.__func__  # type: ignore[attr-defined]
        # Find document by source_id via a direct query
        with db._conn() as conn:
            doc_row = conn.execute(
                "SELECT content_hash, mime_type FROM documents WHERE source_id=? LIMIT 1",
                (source_id,),
            ).fetchone()

        if not doc_row:
            log.warning("No document found for source_id=%s", source_id)
            db.update_citation_verified(citation_id, False)
            failed += 1
            continue

        try:
            text = cache.read_text(doc_row["content_hash"])
            ok = _quote_in_text(quote, text)
        except Exception as e:
            log.warning("Could not read cache for citation %s: %s", citation_id, e)
            ok = False

        db.update_citation_verified(citation_id, ok)
        if ok:
            verified += 1
        else:
            log.warning("Citation %s quote not found in source: %r", citation_id, quote[:60])
            failed += 1

    return verified, failed
