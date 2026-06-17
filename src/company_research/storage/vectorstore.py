from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_EMBED_MODEL = "all-MiniLM-L6-v2"
_DEFAULT_CHUNK_SIZE = 2800    # chars (~400-450 tokens); tuned for SEC filing density
_DEFAULT_CHUNK_OVERLAP = 350  # chars; enough to avoid splitting mid-disclosure


@lru_cache(maxsize=1)
def _get_model():
    from sentence_transformers import SentenceTransformer
    log.info("Loading embedding model %s (first call only)...", _EMBED_MODEL)
    return SentenceTransformer(_EMBED_MODEL)


def _chunk_text(
    text: str,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = _DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """Split text into overlapping chunks, ending on sentence boundaries where possible."""
    chunks: list[str] = []
    start = 0
    boundary_search = min(300, chunk_size // 4)
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if end < len(text):
            m = list(re.finditer(r"[.!?]\s+", chunk[-boundary_search:]))
            if m:
                last = m[-1]
                end = start + (len(chunk) - boundary_search) + last.end()
                chunk = text[start:end]
        chunk = chunk.strip()
        if chunk:
            chunks.append(chunk)
        start = end - chunk_overlap
    return chunks


class VectorStore:
    """Per-symbol ChromaDB collection backed by sentence-transformer embeddings."""

    def __init__(
        self,
        base_dir: Path,
        symbol: str,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = _DEFAULT_CHUNK_OVERLAP,
    ) -> None:
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self.was_reset = False
        import chromadb

        vector_dir = base_dir / ".vector"
        vector_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(vector_dir))
        # ChromaDB names: 3-63 chars, alphanumeric + _ + -
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", symbol.upper())[:63]
        if len(safe_name) < 3:
            safe_name = safe_name + "_co"

        # Check existing collection for chunk param mismatch
        existing = None
        try:
            existing = self._client.get_collection(name=safe_name)
        except Exception:
            pass

        chunk_meta = {"chunk_size": chunk_size, "chunk_overlap": chunk_overlap}

        if existing is not None:
            stored = existing.metadata or {}
            if "chunk_size" in stored and (
                stored["chunk_size"] != chunk_size or stored.get("chunk_overlap") != chunk_overlap
            ):
                log.warning(
                    "Chunk params changed for %s (size %s→%s, overlap %s→%s) — clearing collection for fresh reindex",
                    symbol, stored["chunk_size"], chunk_size, stored.get("chunk_overlap"), chunk_overlap,
                )
                self._client.delete_collection(name=safe_name)
                self._collection = self._client.create_collection(
                    name=safe_name,
                    metadata={"hnsw:space": "cosine", **chunk_meta},
                )
                self.was_reset = True
            else:
                self._collection = existing
                if "chunk_size" not in stored:
                    # Legacy collection — stamp params without clearing
                    self._collection.modify(metadata={**stored, **chunk_meta})
        else:
            self._collection = self._client.create_collection(
                name=safe_name,
                metadata={"hnsw:space": "cosine", **chunk_meta},
            )

        self._symbol = symbol

    def index_document(
        self,
        doc_id: str,
        text: str,
        metadata: dict[str, Any],
    ) -> int:
        """Chunk, embed, and upsert a document. Returns number of chunks stored."""
        chunks = _chunk_text(text, self._chunk_size, self._chunk_overlap)
        if not chunks:
            return 0

        model = _get_model()
        embeddings = model.encode(chunks, show_progress_bar=False, batch_size=32).tolist()

        ids = [f"{doc_id}::{i}" for i in range(len(chunks))]
        metas = [{**metadata, "chunk_idx": i, "doc_id": doc_id} for i in range(len(chunks))]

        self._collection.upsert(ids=ids, embeddings=embeddings, documents=chunks, metadatas=metas)
        log.info("Indexed %d chunks for doc %s into %s", len(chunks), doc_id[:8], self._symbol)
        return len(chunks)

    def retrieve(
        self,
        query: str,
        k: int = 12,
        recency_weight: float = 0.3,
        candidate_multiplier: int = 5,
    ) -> list[dict[str, Any]]:
        """Return top-k chunks using hybrid semantic + recency re-ranking.

        Fetches ``k * candidate_multiplier`` candidates by embedding similarity,
        then re-ranks by::

            hybrid_score = (1 - recency_weight) * semantic_score
                         +      recency_weight  * recency_score

        where ``recency_score`` is linearly normalised over the candidate set's
        date range (most recent = 1.0, oldest = 0.0).  Set ``recency_weight=0``
        to get pure semantic ranking.
        """
        from datetime import date as _date

        n = self._collection.count()
        if n == 0:
            return []

        model = _get_model()
        embedding = model.encode([query], show_progress_bar=False)[0].tolist()

        fetch_k = min(k * candidate_multiplier, n) if recency_weight > 0 else min(k, n)
        results = self._collection.query(
            query_embeddings=[embedding],
            n_results=fetch_k,
            include=["documents", "metadatas", "distances"],
        )

        candidates: list[dict[str, Any]] = []
        for text, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            candidates.append({
                "text": text,
                "metadata": meta,
                "score": round(1.0 - float(dist), 4),
            })

        if recency_weight <= 0 or len(candidates) <= 1:
            return candidates[:k]

        # Parse published_date from chunk metadata
        def _parse(raw: str) -> _date | None:
            if not raw:
                return None
            try:
                return _date.fromisoformat(raw[:10])
            except ValueError:
                return None

        dated = [_parse(c["metadata"].get("published_date", "")) for c in candidates]
        valid = [d for d in dated if d is not None]
        if not valid:
            return candidates[:k]

        min_d, max_d = min(valid), max(valid)
        date_range = max((_date.toordinal(max_d) - _date.toordinal(min_d)), 1)

        reranked: list[dict[str, Any]] = []
        for chunk, d in zip(candidates, dated):
            sem = chunk["score"]
            rec = (_date.toordinal(d) - _date.toordinal(min_d)) / date_range if d else 0.0
            hybrid = (1.0 - recency_weight) * sem + recency_weight * rec
            reranked.append({**chunk, "hybrid_score": round(hybrid, 4)})

        reranked.sort(key=lambda x: x["hybrid_score"], reverse=True)
        return reranked[:k]

    def list_documents(self) -> list[dict]:
        """Return one metadata record per unique document (deduplicated by title)."""
        n = self._collection.count()
        if n == 0:
            return []
        seen: dict[str, dict] = {}
        offset, batch = 0, 500
        while offset < n:
            res = self._collection.get(
                limit=batch, offset=offset, include=["metadatas"]
            )
            if not res["metadatas"]:
                break
            for m in res["metadatas"]:
                title = m.get("title", "")
                if title and title not in seen:
                    seen[title] = {
                        "title": title,
                        "source_type": m.get("source_type", ""),
                        "published_date": m.get("published_date", ""),
                        "period_covered": m.get("period_covered", ""),
                    }
            offset += batch
        return sorted(seen.values(), key=lambda d: d.get("published_date", ""), reverse=True)

    def has_document(self, doc_id: str) -> bool:
        """Return True if at least one chunk for this doc_id exists in the collection."""
        try:
            res = self._collection.get(
                where={"doc_id": {"$eq": doc_id}},
                limit=1,
                include=[],
            )
            return len(res["ids"]) > 0
        except Exception:
            return False

    @property
    def count(self) -> int:
        return self._collection.count()
