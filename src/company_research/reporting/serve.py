"""Local RAG Q&A server for auto-dd research runs.

Starts a single-threaded HTTP server at 127.0.0.1:PORT that:
  GET  /health  → {"status":"ok","symbol":"AAPL"}
  POST /ask     → {"question":"...", "k":12} → {"answer":"...", "sources":[...]}

No new dependencies — uses stdlib http.server + existing anthropic + vectorstore.
"""
from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_PORT = 7234
_MAX_K = 24
_MODEL = "claude-sonnet-4-6"
_SYSTEM = (
    "You are a financial research analyst. Answer questions strictly from the "
    "evidence chunks provided. Cite chunk numbers like [1] inline. "
    "If the evidence is insufficient, say so explicitly — never hallucinate facts."
)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # suppress noisy default stdout
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/health"):
            self._json({"status": "ok", "symbol": self.server.symbol})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path != "/ask":
            self.send_response(404)
            self.end_headers()
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._json({"error": "invalid JSON body"}, 400)
            return

        question = (body.get("question") or "").strip()
        if not question:
            self._json({"error": "empty question"}, 400)
            return

        k = max(1, min(int(body.get("k", 12)), _MAX_K))
        try:
            result = self.server.ask(question, k=k)
            self._json(result)
        except Exception as exc:
            log.exception("RAG ask failed for %r", question)
            self._json({"error": str(exc)}, 500)

    def _json(self, data: dict, status: int = 200):
        payload = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self._cors()
        self.end_headers()
        self.wfile.write(payload)


class RagServer(HTTPServer):
    """Single-symbol RAG server backed by the run's ChromaDB vector store."""

    def __init__(self, run_dir: Path, symbol: str, port: int = DEFAULT_PORT):
        self.run_dir = Path(run_dir)
        self.symbol = symbol.upper()
        self._vs: Any = None
        super().__init__(("127.0.0.1", port), _Handler)

    @property
    def port(self) -> int:
        return self.server_address[1]

    def _get_vs(self):
        if self._vs is None:
            from company_research.storage.vectorstore import VectorStore
            # Vector store lives at output_root/.vector, not inside the run dir.
            # run_dir is research/<SYMBOL>/<date>/ → walk up two levels.
            output_root = self.run_dir.parent.parent
            self._vs = VectorStore(base_dir=output_root, symbol=self.symbol)
        return self._vs

    def _run_source_titles(self) -> set[str] | None:
        """Load allowlist of document titles for this run from sources.json.

        Used as a fallback filter for runs indexed before the own/peers split
        was introduced. For new runs, the own-company VectorStore collection
        already excludes peer documents so no filtering is needed.
        """
        sources_path = self.run_dir / "sources.json"
        if not sources_path.exists():
            return None
        try:
            import json
            sources = json.loads(sources_path.read_text(encoding="utf-8"))
            # Exclude peer sources — they live in the _peers collection now
            return {
                s["title"] for s in sources
                if "title" in s and not s.get("is_peer", False)
            }
        except Exception:
            return None

    def ask(self, question: str, k: int = 12) -> dict:
        import anthropic

        vs = self._get_vs()
        # Hybrid re-ranking: semantic similarity + recency (weight=0.3).
        # The title allowlist is a fallback for old runs where peer docs were
        # mixed into the same collection; new runs use a separate peers collection.
        allowed_titles = self._run_source_titles()
        if allowed_titles:
            # Fetch extra candidates so the title filter has enough to choose from
            raw_chunks = vs.retrieve(question, k=k * 4)
            chunks = [
                c for c in raw_chunks
                if c["metadata"].get("title") in allowed_titles
            ][:k]
        else:
            chunks = vs.retrieve(question, k=k)

        if not chunks:
            return {
                "answer": "No relevant evidence found in the indexed documents for this run.",
                "sources": [],
            }

        ctx_parts = []
        for i, c in enumerate(chunks):
            m = c["metadata"]
            label = f"{m.get('source_type', '?')} — {m.get('title', '')[:70]}"
            ctx_parts.append(f"[{i+1}] {label}\n{c['text']}")
        context = "\n\n---\n\n".join(ctx_parts)

        prompt = (
            f"Research evidence for {self.symbol}:\n\n{context}\n\n"
            f"Question: {question}\n\n"
            "Answer using only the evidence above. "
            "Cite by chunk number [N] where relevant."
        )

        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        answer = msg.content[0].text

        sources = [
            {
                "rank": i + 1,
                "score": round(c.get("hybrid_score", c["score"]), 3),
                "semantic_score": round(c["score"], 3),
                "source_type": c["metadata"].get("source_type", ""),
                "title": c["metadata"].get("title", "")[:80],
                "published_date": c["metadata"].get("published_date", ""),
                "snippet": c["text"][:280] + ("…" if len(c["text"]) > 280 else ""),
            }
            for i, c in enumerate(chunks)
        ]
        return {"answer": answer, "sources": sources}

    def start_background(self) -> threading.Thread:
        """Start serving in a daemon thread. Returns the thread."""
        t = threading.Thread(target=self.serve_forever, daemon=True)
        t.start()
        log.info("RAG server listening on http://127.0.0.1:%d (symbol=%s)", self.port, self.symbol)
        return t
