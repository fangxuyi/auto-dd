# auto-dd

Reproducible CLI pipeline that produces cited, evidence-grounded product-and-business fundamentals reports for public US companies. Every fact in the output traces back to a stored source; the report generator never browses the web.

## What it does

1. Resolves a ticker to a `CompanyIdentity` via SEC EDGAR
2. Discovers sources: EDGAR filings, investor-relations pages, product/pricing pages, web search results, and peer EDGAR filings
3. Fetches and parses all sources into a content-addressed cache
4. Indexes document chunks into a per-symbol vector store (ChromaDB)
5. Extracts XBRL financial metrics and RAG-grounded facts via LLM
6. Detects contradictions, verifies citations, and runs QA gates
7. Generates a structured Markdown report with citations
8. Exports all artifacts to a timestamped output directory

---

## Requirements

- Python 3.11+
- `ANTHROPIC_API_KEY` in environment (or `.env` file)
- No other paid services or API keys required

---

## Installation

```bash
git clone https://github.com/fangxuyi/auto-dd.git
cd auto-dd
pip install -e ".[dev]"
```

---

## Usage

```bash
export ANTHROPIC_API_KEY=sk-...

# Standard analysis (recommended starting point)
company-research analyze AAPL --depth standard --as-of 2026-06-15 --output ./research

# Quick scan (~10 min, fewer sources, no web search)
company-research analyze MSFT --depth quick --output ./research

# Deep analysis (all sources, peer filings, LLM peer ranking)
company-research analyze NVDA --depth deep --output ./research

# Dry run — builds prompts, skips LLM calls, writes run_flow.json
company-research analyze AAPL --depth standard --dry-run --output ./research

# Override RAG top-k
company-research analyze AAPL --depth standard --rag-top-k 32 --output ./research
```

Output is written to `<output>/<SYMBOL>/<AS_OF_DATE>/`.

---

## Output files

| File | Description |
|---|---|
| `report.md` | Full research report with citations |
| `report.html` | Styled HTML version of the report |
| `run_flow.json` | Per-step trace: status, timing, metrics |
| `sources.json` | All sources used in this run |
| `evidence.jsonl` | Extracted facts with source citations |
| `metrics.csv` | XBRL financial metrics (time-series) |
| `peers.json` | Resolved peer companies |
| `company_profile.json` | Entity metadata |
| `contradictions.json` | Detected cross-source contradictions |
| `conclusions.json` | Per-section LLM conclusions |
| `open_questions.json` | Flagged gaps or uncertain items |
| `qa_report.json` | QA gate results (pass/fail per check) |
| `prompts/` | LLM prompt inputs saved in dry-run mode |
| `run.log` | Full pipeline log |

### `run_flow.json` step codes

| Step | Name |
|---|---|
| `1` | Entity Resolution |
| `1b` | External Source Discovery (IR, product, web) |
| `1c` | Peer Selection |
| `2` | EDGAR Source Acquisition |
| `3-4` | Fetch / Parse / Index |
| `5` | XBRL Metric Extraction |
| `6` | RAG Fact Extraction |
| `7` | Contradiction Detection |
| `8` | Citation Verification |
| `9` | Section Analysis |
| `10` | Report Generation |
| `11` | QA Checks |
| `12` | Export |

Status symbols: `✓ completed`, `~ partial`, `– skipped`, `✗ failed`

---

## Architecture

```
CLI (click)
└── Pipeline orchestrator (pipeline.py)
    ├── 1.  EntityResolver      → CompanyIdentity         (EDGAR company_tickers.json)
    ├── 1b. External adapters   → SourceRecord[]
    │       ├── IRPageAdapter   (company investor-relations site)
    │       ├── ProductPageAdapter (product / pricing pages)
    │       └── WebSearchAdapter   (DuckDuckGo HTML, no API key)
    ├── 1c. PeerSelector        → CompanyIdentity[]       (DDG + EDGAR lookup)
    ├── 2.  EdgarAdapter        → SourceRecord[]          (10-K, 10-Q filings)
    ├── 3-4. RawCache + Parsers → NormalizedDocument[]    (HTML, PDF, XBRL, text)
    ├── 5.  XBRLExtractor       → MetricRecord[]
    ├── 6.  FactExtractor (LLM) → EvidenceFact[]          (RAG over vector store)
    ├── 7.  ContradictionDetector (LLM)
    ├── 8.  CitationResolver    (deterministic)
    ├── 9.  SectionAnalyzer (LLM)
    ├── 10. ReportGenerator (LLM) → report.md             (reads evidence store only)
    ├── 11. QARunner            (deterministic)
    └── 12. Exporter
```

### Source reliability tiers

| Tier | Source type | Examples |
|---|---|---|
| 1 | SEC regulatory filings | 10-K, 10-Q |
| 2 | Company operational pages | Product pages, pricing |
| 4 | Credible third-party analysis | Research, analyst summaries |
| 5 | Company IR communications | IR site, press releases, earnings releases |
| 6 | General web media | News articles |

### Storage

- **RawCache** — SQLite content-addressed store; deduplicates by SHA-256 of fetched bytes
- **Database** — SQLite WAL-mode store for runs, sources, facts, metrics, peers, contradictions, QA
- **Vector store** — ChromaDB per-symbol, rebuilt on first run, reused on subsequent runs
- All storage paths default to `~/.company_research/`

---

## Research profiles

Three depth profiles are defined in `config/research_profiles.yaml`:

| Setting | `quick` | `standard` | `deep` |
|---|---|---|---|
| `enable_web_search` | false | true | true |
| `enable_ir_pages` | true | true | true |
| `enable_product_pages` | false | true | true |
| `enable_peer_search` | true | true | true |
| `enable_peer_llm_ranking` | false | false | true |
| `web_search_results_per_query` | 2 | 3 | 5 |
| `max_ir_pages` | 1 | 3 | 8 |
| `max_product_pages` | 1 | 2 | 5 |
| `max_peer_filings` | 2 | 3 | 5 |
| `rag_top_k` | 64 | 64 | 64 |

---

## Development

```bash
# Unit tests — no network, no API key
pytest tests/unit/ -v

# Integration / live tests
pytest tests/ -m live

# Lint
ruff check src/ tests/

# Type check
mypy src/
```

Tests are in `tests/unit/` (100 tests) and `tests/integration/`. All unit tests use mocked HTTP and no live credentials.

---

## Key design constraints

- **Evidence-only output**: the report generator reads only from the SQLite evidence store. It never browses the web.
- **No paid dependencies**: DuckDuckGo HTML scraping requires no API key. All other sources are public (SEC EDGAR).
- **Graded degradation**: failures in external adapters (network errors, CAPTCHA/rate-limiting) are logged at WARNING and do not abort the run.
- **Idempotent storage**: all cache and DB writes are content-hash deduplicated.
- **Audit trail**: every fact carries `source_id`, `location`, `period`, `unit`, `extraction_method`, `confidence`. Every run records `model_id`, prompt versions, and config.
- **No credential commits**: never commit `.env` files, API keys, cookies, or copyrighted paid reports.

---

## Project structure

```
auto-dd/
├── config/
│   ├── research_profiles.yaml   # depth profiles
│   └── source_priority.yaml     # source selection weights
├── guidelines/                  # analysis template (read before changing research logic)
├── prompts/                     # versioned LLM prompts (YAML front matter)
├── src/company_research/
│   ├── cli.py                   # click entrypoint
│   ├── pipeline.py              # orchestrator
│   ├── pipeline_flow.py         # run_flow.json recorder
│   ├── config.py                # profile loader
│   ├── models/                  # Pydantic schemas
│   ├── identity/                # entity resolver (EDGAR)
│   ├── sources/                 # SourceAdapter implementations
│   │   ├── edgar.py
│   │   ├── web_search.py        # DuckDuckGo HTML
│   │   ├── ir_page.py           # investor-relations crawler
│   │   ├── product_page.py      # product/pricing crawler
│   │   └── peer_selector.py     # DDG + EDGAR peer resolution
│   ├── parsing/                 # HTML, PDF, XBRL, text parsers
│   ├── extraction/              # fact extractor, XBRL extractor
│   ├── analysis/                # section analyzer, contradiction detector
│   ├── reporting/               # report generator, formatter
│   ├── validation/              # QA gates, citation resolver
│   ├── llm/                     # Anthropic LLM interface
│   └── storage/                 # SQLite DB, raw cache, export
└── tests/
    ├── unit/                    # mocked, no network (100 tests)
    └── integration/             # requires network and API key
```
