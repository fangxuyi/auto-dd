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
    is_peer INTEGER NOT NULL DEFAULT 0,
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

-- ── value chain tables ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS vc_entities (
    entity_id TEXT PRIMARY KEY,
    legal_name TEXT NOT NULL,
    common_name TEXT,
    ticker TEXT,
    exchange TEXT,
    country TEXT,
    security_type TEXT,
    primary_listing INTEGER DEFAULT 1,
    adr_status INTEGER DEFAULT 0,
    operating_subsidiary TEXT,
    ultimate_public_parent TEXT,
    regulator_id TEXT,
    isin TEXT,
    active_listing INTEGER DEFAULT 1,
    as_of_date TEXT,
    aliases TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS vc_entity_aliases (
    alias_id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    alias TEXT NOT NULL,
    alias_type TEXT,
    FOREIGN KEY (entity_id) REFERENCES vc_entities(entity_id)
);

CREATE TABLE IF NOT EXISTS vc_layers (
    layer_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    layer_name TEXT NOT NULL,
    description TEXT,
    layer_order INTEGER DEFAULT 0,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS vc_relationship_candidates (
    candidate_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    raw_name TEXT NOT NULL,
    normalized_name TEXT,
    source_id TEXT,
    source_excerpt TEXT,
    proposed_layer TEXT,
    proposed_relationship_type TEXT,
    resolved_entity_id TEXT,
    resolution_status TEXT DEFAULT 'unresolved',
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS vc_relationships (
    relationship_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    source_entity_id TEXT NOT NULL,
    target_entity_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    value_chain_layer TEXT,
    product_or_service TEXT,
    geography TEXT,
    start_date TEXT,
    end_date TEXT,
    current_status TEXT DEFAULT 'unverified_candidate',
    evidence_status TEXT DEFAULT 'unverified',
    confidence TEXT DEFAULT 'unknown',
    materiality TEXT DEFAULT 'unknown',
    exclusivity INTEGER,
    source_ids TEXT DEFAULT '[]',
    source_locations TEXT DEFAULT '[]',
    last_verified_date TEXT,
    analyst_notes TEXT,
    reverse_verified INTEGER DEFAULT 0,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS vc_relationship_evidence (
    evidence_id TEXT PRIMARY KEY,
    relationship_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_location TEXT,
    excerpt TEXT,
    evidence_status TEXT DEFAULT 'unverified',
    direction TEXT DEFAULT 'target_first',
    verified_date TEXT,
    FOREIGN KEY (relationship_id) REFERENCES vc_relationships(relationship_id)
);

CREATE TABLE IF NOT EXISTS vc_dependency_assessments (
    assessment_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    relationship_id TEXT NOT NULL,
    target_dependency_score INTEGER,
    counterparty_dependency_score INTEGER,
    target_dependency_rationale TEXT,
    counterparty_dependency_rationale TEXT,
    switching_cost_notes TEXT,
    alternatives_exist INTEGER,
    qualification_time_months INTEGER,
    contract_duration_months INTEGER,
    confidence TEXT DEFAULT 'unknown',
    FOREIGN KEY (relationship_id) REFERENCES vc_relationships(relationship_id)
);

CREATE TABLE IF NOT EXISTS vc_profit_pool_assessments (
    assessment_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    layer_name TEXT NOT NULL,
    representative_companies TEXT DEFAULT '[]',
    gross_margin_range TEXT,
    operating_margin_range TEXT,
    roic_range TEXT,
    capital_intensity TEXT DEFAULT 'unknown',
    concentration TEXT DEFAULT 'unknown',
    pricing_power TEXT DEFAULT 'unknown',
    trend TEXT DEFAULT 'unknown',
    notes TEXT
);

CREATE TABLE IF NOT EXISTS vc_chokepoints (
    chokepoint_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    chokepoint TEXT NOT NULL,
    owner_or_controller TEXT,
    affected_product TEXT,
    failure_mechanism TEXT,
    replacement_time TEXT,
    financial_effect TEXT,
    early_warning_indicators TEXT DEFAULT '[]',
    mitigation TEXT,
    confidence TEXT DEFAULT 'unknown'
);

CREATE TABLE IF NOT EXISTS vc_graph_nodes (
    node_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    entity_name TEXT NOT NULL,
    entity_type TEXT,
    public_status TEXT DEFAULT 'unknown',
    ticker TEXT,
    exchange TEXT,
    country TEXT,
    industry TEXT,
    value_chain_layers TEXT DEFAULT '[]',
    ultimate_public_parent TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS vc_graph_edges (
    edge_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    source_node_id TEXT NOT NULL,
    target_node_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    product_or_service TEXT,
    status TEXT DEFAULT 'unverified_candidate',
    confidence TEXT DEFAULT 'unknown',
    materiality TEXT DEFAULT 'unknown',
    start_date TEXT,
    end_date TEXT,
    source_ids TEXT DEFAULT '[]',
    last_verified_date TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_vc_relationships_run ON vc_relationships(run_id);
CREATE INDEX IF NOT EXISTS idx_vc_candidates_run ON vc_relationship_candidates(run_id);
CREATE INDEX IF NOT EXISTS idx_vc_entities_ticker ON vc_entities(ticker);
"""


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            # Migrations for columns added after initial schema
            existing = {r[1] for r in conn.execute("PRAGMA table_info(sources)").fetchall()}
            if "is_peer" not in existing:
                conn.execute("ALTER TABLE sources ADD COLUMN is_peer INTEGER NOT NULL DEFAULT 0")

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

    def upsert_source(self, source: SourceRecord, run_id: str, is_peer: bool = False) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO sources
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(source_id) DO NOTHING""",
                (
                    source.source_id, run_id, source.title, source.publisher,
                    source.url,
                    source.published_date.isoformat() if source.published_date else None,
                    source.accessed_date.isoformat(), source.source_type,
                    source.primary_or_secondary, source.period_covered,
                    source.company_or_external, source.reliability_tier,
                    1 if is_peer else 0,
                ),
            )

    def get_sources(self, run_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM sources WHERE run_id=?", (run_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_sources_for_symbol(self, symbol: str) -> list[dict]:
        """Return own-company sources across every run for a symbol, deduplicated by URL."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT s.* FROM sources s
                   JOIN runs r ON s.run_id = r.run_id
                   WHERE r.symbol = ? AND s.is_peer = 0
                   ORDER BY s.published_date DESC""",
                (symbol.upper(),),
            ).fetchall()
            seen: set[str] = set()
            result: list[dict] = []
            for row in rows:
                d = dict(row)
                key = d["url"] or d["source_id"]
                if key not in seen:
                    seen.add(key)
                    result.append(d)
            return result

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

    def get_document_by_source_id(self, source_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE source_id=? LIMIT 1", (source_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_document_by_url(self, url: str) -> dict | None:
        """Find a cached document by source URL (joins sources → documents across all runs)."""
        with self._conn() as conn:
            row = conn.execute(
                """SELECT d.* FROM documents d
                   JOIN sources s ON d.source_id = s.source_id
                   WHERE s.url=? LIMIT 1""",
                (url,),
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

    # --- run queries ---

    def get_latest_run(self, symbol: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT * FROM runs WHERE symbol=? AND status IN ('completed','partial')
                   ORDER BY as_of_date DESC, started_at DESC LIMIT 1""",
                (symbol.upper(),),
            ).fetchone()
            return dict(row) if row else None

    def get_run_by_id(self, run_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            return dict(row) if row else None

    def list_runs(self, symbol: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM runs WHERE symbol=? ORDER BY as_of_date DESC, started_at DESC",
                (symbol.upper(),),
            ).fetchall()
            return [dict(r) for r in rows]

    # --- metric queries ---

    def get_metrics_by_name(self, run_id: str, name: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM metrics WHERE run_id=? AND name=? ORDER BY period",
                (run_id, name),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_distinct_metric_names(self, run_id: str) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT name FROM metrics WHERE run_id=? ORDER BY name",
                (run_id,),
            ).fetchall()
            return [r[0] for r in rows]

    # --- sources by date ---

    def get_sources_since(self, symbol: str, since_date: str) -> list[dict]:
        """Return all sources for symbol whose published_date > since_date."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT s.* FROM sources s
                   JOIN runs r ON s.run_id = r.run_id
                   WHERE r.symbol=? AND s.published_date > ?
                   ORDER BY s.published_date DESC""",
                (symbol.upper(), since_date),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── value chain ───────────────────────────────────────────────────────────

    def upsert_vc_entity(self, entity: "PublicEntityIdentity") -> None:
        import json as _json
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO vc_entities VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(entity_id) DO UPDATE SET
                     legal_name=excluded.legal_name, common_name=excluded.common_name,
                     ticker=excluded.ticker, exchange=excluded.exchange,
                     ultimate_public_parent=excluded.ultimate_public_parent,
                     active_listing=excluded.active_listing""",
                (
                    entity.entity_id, entity.legal_name, entity.common_name,
                    entity.ticker, entity.exchange, entity.country,
                    entity.security_type, int(entity.primary_listing), int(entity.adr_status),
                    entity.operating_subsidiary, entity.ultimate_public_parent,
                    entity.regulator_id, entity.isin, int(entity.active_listing),
                    entity.as_of_date.isoformat() if entity.as_of_date else None,
                    _json.dumps(entity.aliases),
                ),
            )

    def get_vc_entity(self, entity_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM vc_entities WHERE entity_id=?", (entity_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_vc_entity_by_ticker(self, ticker: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM vc_entities WHERE ticker=? LIMIT 1", (ticker.upper(),)
            ).fetchone()
            return dict(row) if row else None

    def upsert_vc_layer(self, layer: "ValueChainLayer") -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO vc_layers VALUES (?,?,?,?,?,?)
                   ON CONFLICT(layer_id) DO NOTHING""",
                (layer.layer_id, layer.run_id, layer.symbol,
                 layer.layer_name, layer.description, layer.order),
            )

    def get_vc_layers(self, run_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM vc_layers WHERE run_id=? ORDER BY layer_order", (run_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def upsert_vc_candidate(self, candidate: "EntityCandidate") -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO vc_relationship_candidates VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(candidate_id) DO UPDATE SET
                     resolution_status=excluded.resolution_status,
                     resolved_entity_id=excluded.resolved_entity_id""",
                (
                    candidate.candidate_id, candidate.run_id, candidate.raw_name,
                    candidate.normalized_name, candidate.source_id, candidate.source_excerpt,
                    candidate.proposed_layer, candidate.proposed_relationship_type,
                    candidate.resolved_entity_id, candidate.resolution_status,
                ),
            )

    def get_vc_candidates(self, run_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM vc_relationship_candidates WHERE run_id=?", (run_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def upsert_vc_relationship(self, rel: "CompanyRelationship") -> None:
        import json as _json
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO vc_relationships VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(relationship_id) DO UPDATE SET
                     current_status=excluded.current_status,
                     evidence_status=excluded.evidence_status,
                     confidence=excluded.confidence,
                     reverse_verified=excluded.reverse_verified,
                     last_verified_date=excluded.last_verified_date""",
                (
                    rel.relationship_id, rel.run_id, rel.source_entity_id, rel.target_entity_id,
                    rel.relationship_type, rel.value_chain_layer, rel.product_or_service,
                    rel.geography,
                    rel.start_date.isoformat() if rel.start_date else None,
                    rel.end_date.isoformat() if rel.end_date else None,
                    rel.current_status, rel.evidence_status, rel.confidence, rel.materiality,
                    int(rel.exclusivity) if rel.exclusivity is not None else None,
                    _json.dumps(rel.source_ids), _json.dumps(rel.source_locations),
                    rel.last_verified_date.isoformat() if rel.last_verified_date else None,
                    rel.analyst_notes, int(rel.reverse_verified),
                ),
            )

    def get_vc_relationships(self, run_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM vc_relationships WHERE run_id=?", (run_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def update_relationship_product(self, relationship_id: str, product_or_service: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE vc_relationships SET product_or_service=? WHERE relationship_id=?",
                (product_or_service, relationship_id),
            )

    def upsert_vc_relationship_evidence(self, ev: "RelationshipEvidence") -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO vc_relationship_evidence VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(evidence_id) DO NOTHING""",
                (
                    ev.evidence_id, ev.relationship_id, ev.source_id, ev.source_location,
                    ev.excerpt, ev.evidence_status, ev.direction,
                    ev.verified_date.isoformat() if ev.verified_date else None,
                ),
            )

    def upsert_vc_dependency(self, dep: "DependencyAssessment") -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO vc_dependency_assessments VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(assessment_id) DO UPDATE SET
                     target_dependency_score=excluded.target_dependency_score,
                     counterparty_dependency_score=excluded.counterparty_dependency_score""",
                (
                    dep.assessment_id, dep.run_id, dep.relationship_id,
                    dep.target_dependency_score, dep.counterparty_dependency_score,
                    dep.target_dependency_rationale, dep.counterparty_dependency_rationale,
                    dep.switching_cost_notes,
                    int(dep.alternatives_exist) if dep.alternatives_exist is not None else None,
                    dep.qualification_time_months, dep.contract_duration_months, dep.confidence,
                ),
            )

    def upsert_vc_profit_pool(self, pp: "ProfitPoolAssessment") -> None:
        import json as _json
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO vc_profit_pool_assessments VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(assessment_id) DO UPDATE SET
                     gross_margin_range=excluded.gross_margin_range,
                     operating_margin_range=excluded.operating_margin_range""",
                (
                    pp.assessment_id, pp.run_id, pp.layer_name,
                    _json.dumps(pp.representative_companies),
                    pp.gross_margin_range, pp.operating_margin_range, pp.roic_range,
                    pp.capital_intensity, pp.concentration, pp.pricing_power, pp.trend, pp.notes,
                ),
            )

    def get_vc_profit_pools(self, run_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM vc_profit_pool_assessments WHERE run_id=?", (run_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def upsert_vc_chokepoint(self, cp: "ChokepointAssessment") -> None:
        import json as _json
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO vc_chokepoints VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(chokepoint_id) DO NOTHING""",
                (
                    cp.chokepoint_id, cp.run_id, cp.chokepoint, cp.owner_or_controller,
                    cp.affected_product, cp.failure_mechanism, cp.replacement_time,
                    cp.financial_effect, _json.dumps(cp.early_warning_indicators),
                    cp.mitigation, cp.confidence,
                ),
            )

    def get_vc_chokepoints(self, run_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM vc_chokepoints WHERE run_id=?", (run_id,)
            ).fetchall()
            return [dict(r) for r in rows]
