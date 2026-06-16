from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from company_research.models import (
    Citation,
    CompanyIdentity,
    Contradiction,
    EvidenceFact,
    MetricObservation,
    OpenQuestion,
    QAResult,
    ResearchRun,
    SectionConclusion,
    SourceRecord,
    RawDocument,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    cik TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    issuer_name TEXT NOT NULL,
    lei TEXT,
    isin TEXT,
    fiscal_year_end TEXT NOT NULL,
    currency TEXT NOT NULL,
    ir_url TEXT,
    filing_jurisdiction TEXT NOT NULL,
    security_type TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    depth TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    lookback_years INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    model_id TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    code_commit TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    output_dir TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    title TEXT NOT NULL,
    publisher TEXT NOT NULL,
    url TEXT NOT NULL,
    published_date TEXT,
    accessed_date TEXT NOT NULL,
    source_type TEXT NOT NULL,
    primary_or_secondary TEXT NOT NULL,
    period_covered TEXT,
    company_or_external TEXT NOT NULL,
    reliability_tier INTEGER NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    file_path TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    retrieved_at TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES sources(source_id)
);

CREATE TABLE IF NOT EXISTS facts (
    fact_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    topic TEXT NOT NULL,
    claim TEXT NOT NULL,
    value TEXT,
    unit TEXT,
    period TEXT,
    source_id TEXT NOT NULL,
    source_location TEXT NOT NULL,
    fact_claim_or_inference TEXT NOT NULL,
    extraction_method TEXT NOT NULL,
    confidence TEXT NOT NULL,
    notes TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(run_id),
    FOREIGN KEY (source_id) REFERENCES sources(source_id)
);

CREATE TABLE IF NOT EXISTS metrics (
    metric_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    name TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT NOT NULL,
    period TEXT NOT NULL,
    period_type TEXT NOT NULL,
    value_type TEXT NOT NULL,
    currency TEXT,
    source_id TEXT NOT NULL,
    notes TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(run_id),
    FOREIGN KEY (source_id) REFERENCES sources(source_id)
);

CREATE TABLE IF NOT EXISTS contradictions (
    contradiction_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    fact_id_a TEXT NOT NULL,
    fact_id_b TEXT NOT NULL,
    description TEXT NOT NULL,
    severity TEXT NOT NULL,
    resolution TEXT,
    resolved INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS conclusions (
    conclusion_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    section TEXT NOT NULL,
    conclusion TEXT NOT NULL,
    supporting_fact_ids TEXT NOT NULL,
    counterevidence TEXT,
    confidence TEXT NOT NULL,
    open_questions TEXT NOT NULL,
    monitoring_indicators TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS citations (
    citation_id TEXT PRIMARY KEY,
    fact_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    location TEXT NOT NULL,
    quote TEXT,
    verified INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (fact_id) REFERENCES facts(fact_id),
    FOREIGN KEY (source_id) REFERENCES sources(source_id)
);

CREATE TABLE IF NOT EXISTS open_questions (
    question_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    question TEXT NOT NULL,
    why_it_matters TEXT NOT NULL,
    best_source TEXT,
    current_hypothesis TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS peers (
    run_id TEXT NOT NULL,
    peer_symbol TEXT NOT NULL,
    peer_name TEXT,
    peer_cik TEXT,
    rationale TEXT,
    PRIMARY KEY (run_id, peer_symbol),
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_facts_run ON facts(run_id);
CREATE INDEX IF NOT EXISTS idx_facts_source ON facts(source_id);
CREATE INDEX IF NOT EXISTS idx_sources_run ON sources(run_id);
CREATE INDEX IF NOT EXISTS idx_metrics_run ON metrics(run_id);
CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(content_hash);
"""


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # --- companies ---

    def upsert_company(self, company: CompanyIdentity) -> None:
        from datetime import datetime
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO companies VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(cik) DO UPDATE SET
                     symbol=excluded.symbol, exchange=excluded.exchange,
                     issuer_name=excluded.issuer_name, lei=excluded.lei,
                     isin=excluded.isin, fiscal_year_end=excluded.fiscal_year_end,
                     currency=excluded.currency, ir_url=excluded.ir_url,
                     filing_jurisdiction=excluded.filing_jurisdiction,
                     security_type=excluded.security_type,
                     updated_at=excluded.updated_at""",
                (
                    company.cik, company.symbol, company.exchange,
                    company.issuer_name, company.lei, company.isin,
                    company.fiscal_year_end, company.currency, company.ir_url,
                    company.filing_jurisdiction, company.security_type,
                    datetime.utcnow().isoformat(),
                ),
            )

    # --- runs ---

    def insert_run(self, run: ResearchRun) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run.run_id, run.symbol, run.depth,
                    run.as_of_date.isoformat(), run.lookback_years,
                    run.started_at.isoformat(),
                    run.completed_at.isoformat() if run.completed_at else None,
                    run.status, run.model_id, run.prompt_version,
                    run.code_commit, run.config_hash, run.output_dir,
                ),
            )

    def update_run_status(
        self, run_id: str, status: str, completed_at: str | None = None
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE runs SET status=?, completed_at=? WHERE run_id=?",
                (status, completed_at, run_id),
            )

    # --- sources ---

    def upsert_source(self, source: SourceRecord, run_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO sources VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(source_id) DO NOTHING""",
                (
                    source.source_id, run_id, source.title, source.publisher,
                    source.url,
                    source.published_date.isoformat() if source.published_date else None,
                    source.accessed_date.isoformat(), source.source_type,
                    source.primary_or_secondary, source.period_covered,
                    source.company_or_external, source.reliability_tier,
                ),
            )

    def get_sources(self, run_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM sources WHERE run_id=?", (run_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    # --- documents ---

    def upsert_document(self, doc: RawDocument) -> bool:
        """Returns True if inserted (new), False if already existed."""
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO documents VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(content_hash) DO NOTHING""",
                (
                    doc.doc_id, doc.source_id, doc.content_hash,
                    doc.file_path, doc.mime_type, doc.size_bytes,
                    doc.retrieved_at.isoformat(),
                ),
            )
            return cur.rowcount > 0

    def get_document_by_hash(self, content_hash: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE content_hash=?", (content_hash,)
            ).fetchone()
            return dict(row) if row else None

    # --- facts ---

    def insert_fact(self, fact: EvidenceFact) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    fact.fact_id, fact.run_id, fact.topic, fact.claim,
                    fact.value, fact.unit, fact.period,
                    fact.source_id, fact.source_location,
                    fact.fact_claim_or_inference, fact.extraction_method,
                    fact.confidence, fact.notes,
                ),
            )

    def get_facts(self, run_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM facts WHERE run_id=?", (run_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    # --- metrics ---

    def insert_metric(self, metric: MetricObservation) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO metrics VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    metric.metric_id, metric.run_id, metric.name,
                    metric.value, metric.unit, metric.period,
                    metric.period_type, metric.value_type,
                    metric.currency, metric.source_id, metric.notes,
                ),
            )

    def get_metrics(self, run_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM metrics WHERE run_id=?", (run_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    # --- contradictions ---

    def insert_contradiction(self, c: Contradiction) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO contradictions VALUES (?,?,?,?,?,?,?,?)",
                (
                    c.contradiction_id, c.run_id, c.fact_id_a, c.fact_id_b,
                    c.description, c.severity, c.resolution, int(c.resolved),
                ),
            )

    def get_contradictions(self, run_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM contradictions WHERE run_id=?", (run_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    # --- conclusions ---

    def insert_conclusion(self, c: SectionConclusion) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO conclusions VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    c.conclusion_id, c.run_id, c.section, c.conclusion,
                    json.dumps(c.supporting_fact_ids), c.counterevidence,
                    c.confidence, json.dumps(c.open_questions),
                    json.dumps(c.monitoring_indicators),
                ),
            )

    def get_conclusions(self, run_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM conclusions WHERE run_id=?", (run_id,)
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["supporting_fact_ids"] = json.loads(d["supporting_fact_ids"])
                d["open_questions"] = json.loads(d["open_questions"])
                d["monitoring_indicators"] = json.loads(d["monitoring_indicators"])
                result.append(d)
            return result

    # --- citations ---

    def insert_citation(self, c: Citation) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO citations VALUES (?,?,?,?,?,?)",
                (
                    c.citation_id, c.fact_id, c.source_id,
                    c.location, c.quote, int(c.verified),
                ),
            )

    def update_citation_verified(self, citation_id: str, verified: bool) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE citations SET verified=? WHERE citation_id=?",
                (int(verified), citation_id),
            )

    def get_citations(self, run_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT c.* FROM citations c
                   JOIN facts f ON c.fact_id = f.fact_id
                   WHERE f.run_id=?""",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # --- open questions ---

    def insert_question(self, q: OpenQuestion) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO open_questions VALUES (?,?,?,?,?,?,?)",
                (
                    q.question_id, q.run_id, q.question, q.why_it_matters,
                    q.best_source, q.current_hypothesis, q.status,
                ),
            )

    def get_questions(self, run_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM open_questions WHERE run_id=?", (run_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    # --- peers ---

    def upsert_peer(
        self, run_id: str, peer_symbol: str, peer_name: str = "", peer_cik: str = "", rationale: str = ""
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO peers (run_id, peer_symbol, peer_name, peer_cik, rationale)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(run_id, peer_symbol) DO UPDATE SET
                     peer_name=excluded.peer_name, peer_cik=excluded.peer_cik,
                     rationale=excluded.rationale""",
                (run_id, peer_symbol, peer_name, peer_cik, rationale),
            )

    def get_peers(self, run_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM peers WHERE run_id=?", (run_id,)
            ).fetchall()
            return [dict(r) for r in rows]
