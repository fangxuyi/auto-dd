# auto-dd

Reproducible CLI pipeline that produces cited, evidence-grounded product-and-business fundamentals reports for public US companies. Every fact in the output traces back to a stored source; the report generator never browses the web.

---

## What it does

1. Resolves a ticker to a `CompanyIdentity` via SEC EDGAR
2. Discovers sources: EDGAR filings, investor-relations pages, product/pricing pages, web search results, and peer EDGAR filings
3. Fetches and parses all sources into a content-addressed cache
4. Indexes document chunks into a per-symbol vector store (ChromaDB)
5. Extracts XBRL financial metrics and RAG-grounded facts via LLM
6. Detects contradictions, verifies citations, and runs QA gates
7. Generates a structured Markdown report with citations
8. Maps the supply-chain value chain from EDGAR reverse lookup
9. Exports a self-contained HTML report with interactive value chain graph and RAG Q&A

---

## Requirements

- Python 3.11+
- `ANTHROPIC_API_KEY` in environment or `.env` file
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

### One command — full pipeline

```bash
company-research research AAPL --depth quick
```

Runs **analyze → value-chain → HTML → RAG server** in sequence and opens the report in your browser. The browser report has four tabs: Report, Value Chain, Sources, Ask.

Options:
- `--depth quick|standard|deep` — research depth (default: `quick`)
- `--no-value-chain` — skip the value chain step
- `--no-serve` — generate everything but don't start the RAG server
- `--port 7234` — RAG server port

---

### Individual commands

```bash
# Analyze only — produces report.md and all artifacts
company-research analyze AAPL --depth standard --as-of 2026-06-15 --output ./research

# Value chain — maps supply-chain relationships from EDGAR
company-research value-chain AAPL --depth quick

# Convert report.md to HTML (auto-detects value_chain_graph.json next to it)
company-research to-html research/AAPL/2026-06-15/report.md

# Start local RAG server for Q&A against indexed evidence
company-research serve research/AAPL/2026-06-15/report.md --port 7234
```

Output is written to `<output>/<SYMBOL>/<AS_OF_DATE>/`.

---

## HTML report

`to-html` generates a self-contained HTML file with four tabs:

| Tab | Contents |
|---|---|
| **Report** | Full research report with citations, conclusions, confidence ratings |
| **Value Chain** | D3 force-directed graph (amber = upstream suppliers, teal = downstream customers) + split relationship tables with Product/Service, Relationship, Confidence, and Materiality columns. Hover any table row to see the SEC filing reference that sourced the relationship. |
| **Sources** | All indexed documents with type, publisher, date, and reliability tier |
| **Ask** | Interactive RAG Q&A panel — type a question, get an evidence-grounded answer with inline citations |

The Ask tab connects to the local RAG server (`company-research serve`). The command to start it is always visible on the Ask tab with a one-click Copy button.

---

## Output files

| File | Description |
|---|---|
| `report.md` | Full research report with citations |
| `report.html` | Tabbed HTML report (value chain + RAG Q&A) |
| `value_chain_report.md` | Value chain narrative and relationship summary |
| `value_chain_graph.json` | Graph nodes and edges with product/service labels and SEC filing excerpts (embedded in HTML) |
| `value_chain_nodes.csv` | Node list: ticker, entity name, exchange, country |
| `value_chain_edges.csv` | Edge list: relationship type, confidence, materiality |
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

---

## Architecture

```
CLI (click)
└── Pipeline orchestrator (pipeline.py)
    ├── 1.  EntityResolver      → CompanyIdentity         (EDGAR company_tickers.json)
    ├── 1b. External adapters   → SourceRecord[]
    │       ├── IRPageAdapter      (investor-relations site)
    │       ├── ProductPageAdapter (product / pricing pages)
    │       └── WebSearchAdapter   (DuckDuckGo, no API key)
    ├── 1c. PeerSelector        → CompanyIdentity[]       (DDG + EDGAR lookup)
    ├── 2.  EdgarAdapter        → SourceRecord[]          (10-K, 10-Q filings)
    ├── 3-4. RawCache + Parsers → NormalizedDocument[]
    ├── 5.  XBRLExtractor       → MetricRecord[]
    ├── 6.  FactExtractor (LLM) → EvidenceFact[]
    ├── 7.  ContradictionDetector (LLM)
    ├── 8.  CitationResolver    (deterministic)
    ├── 9.  SectionAnalyzer (LLM)
    ├── 10. ReportGenerator (LLM) → report.md
    ├── 11. QARunner            (deterministic)
    └── 12. Exporter            → report.html, value_chain_graph.json, sources.json …

Value chain pipeline (pipeline_value_chain.py)
    ├── VC-2.  Decompose value chain layers (industry template)
    ├── VC-3.  Forward EDGAR discovery (target's own filings)
    ├── VC-3b. Reverse EDGAR lookup ("Apple Inc." mentions in third-party 10-Ks)
    │           Two queries: "customer" → SUPPLIES relationship
    │                        "supplier" → CUSTOMER_OF relationship (downstream)
    ├── VC-4.  Resolve candidates to EDGAR entities
    ├── VC-5.  Build relationship records
    ├── VC-5b. Product/service extraction (claude-haiku-4-5, ~$0.006/run)
    │           Extracts 3–7 word label per relationship from filing excerpt
    ├── VC-6.  Assess dependencies
    ├── VC-7.  Build profit pool stubs
    ├── VC-8.  Identify chokepoints
    ├── VC-9.  Assemble graph → value_chain_graph.json (includes source_excerpt per edge)
    └── VC-10. Write value_chain_report.md

Reporting
    ├── html_export.py  convert()  → self-contained 4-tab HTML
    └── serve.py        RagServer  → GET /health, POST /ask (VectorStore + Claude)
```

### Value chain relationships

The reverse EDGAR lookup finds companies that name the target in their own SEC filings:

| Filing says… | Relationship | Direction in graph |
|---|---|---|
| "Apple Inc. is our **customer**" | `SUPPLIES` | Filer → AAPL (upstream supplier, amber) |
| "Apple Inc. is our **supplier**" | `CUSTOMER_OF` | AAPL → Filer (downstream customer, teal) |

Each relationship is enriched with a product/service label extracted by `claude-haiku-4-5-20251001` from the filing excerpt, at roughly $0.006 per full run. The label and the raw filing sentence are both surfaced in the HTML report (hover any table row to see the source).

---

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
- **VectorStore** — ChromaDB, shared per output root, queried per-run via title allowlist
- All storage paths default to `./research/`

---

## Research profiles

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

## Estimated cost per run

All LLM calls use Claude models via the Anthropic API. EDGAR, DuckDuckGo, IR pages, and product pages are free/public — no cost.

**Baseline: AAPL `--depth quick`** (measured run, 2026-06-16)

| Step | Model | Calls | Input tokens | Output tokens | Cost |
|---|---|---|---|---|---|
| `extract_facts` | Sonnet 4.6 | 18 | 183,597 | 145,649 | $2.74 |
| `analyze_section` | Sonnet 4.6 | 17 | 160,719 | 24,945 | $0.86 |
| `detect_counterevidence` | Sonnet 4.6 | 3 | 118,165 | 5,932 | $0.44 |
| `synthesize_report` | Sonnet 4.6 | 2 | 12,537 | 11,581 | $0.21 |
| `extract_products` (VC-5b) | Haiku 4.5 | ~56 | ~5,600 | ~560 | $0.006 |
| **Total** | | **~96** | **~481K** | **~188K** | **~$4.26** |

Pricing used: Sonnet 4.6 at $3.00/M input + $15.00/M output; Haiku 4.5 at $0.80/M input + $4.00/M output.

**Scaling by depth**

- `--depth quick`: ~$4–5 (measured above; web search disabled, fewer sources)
- `--depth standard`: ~$8–12 (web search + product pages add more chunks → more `extract_facts` calls)
- `--depth deep`: ~$15–25 (maximum sources, peer LLM ranking, additional peer filings)

The dominant cost driver is `extract_facts` — it scales with the number of source chunks indexed. Each additional source (IR page, web search result, peer filing) adds roughly 8–15K input tokens to the extraction pass.

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

---

## Key design constraints

- **Evidence-only output**: the report generator reads only from the SQLite evidence store — never browses the web.
- **RAG Q&A scoped to run**: the `/ask` endpoint filters vector store results to documents indexed in the current run, using the `sources.json` title allowlist.
- **No paid dependencies**: DuckDuckGo requires no API key. All other sources are public (SEC EDGAR).
- **Graded degradation**: failures in external adapters are logged at WARNING and do not abort the run.
- **Idempotent storage**: all cache and DB writes are content-hash deduplicated.
- **Audit trail**: every fact carries `source_id`, `location`, `period`, `unit`, `extraction_method`, `confidence`. Every run records `model_id`, prompt versions, and config.
- **No credential commits**: never commit `.env` files, API keys, cookies, or copyrighted paid reports.

---

## Project structure

```
auto-dd/
├── config/
│   ├── research_profiles.yaml      # depth profiles
│   └── source_priority.yaml        # source selection weights
├── guidelines/                     # analysis template
├── prompts/                        # versioned LLM prompts (YAML front matter)
├── src/company_research/
│   ├── cli.py                      # click entrypoint (analyze, value-chain, to-html, serve, research)
│   ├── pipeline.py                 # main orchestrator
│   ├── pipeline_value_chain.py     # value chain orchestrator
│   ├── pipeline_flow.py            # run_flow.json recorder
│   ├── config.py                   # profile loader
│   ├── models/                     # Pydantic schemas
│   ├── identity/                   # entity resolver (EDGAR)
│   ├── sources/                    # SourceAdapter implementations
│   │   ├── edgar.py
│   │   ├── web_search.py           # DuckDuckGo (no API key)
│   │   ├── ir_page.py              # investor-relations crawler
│   │   ├── product_page.py         # product/pricing crawler
│   │   └── peer_selector.py        # DDG + EDGAR peer resolution
│   ├── parsing/                    # HTML, PDF, XBRL, text parsers
│   ├── extraction/                 # fact extractor, XBRL extractor
│   ├── analysis/                   # section analyzer, contradiction detector
│   ├── reporting/
│   │   ├── generator.py            # LLM report writer
│   │   ├── html_export.py          # 4-tab self-contained HTML
│   │   └── serve.py                # local RAG server (stdlib http.server)
│   ├── validation/                 # QA gates, citation resolver
│   ├── llm/                        # Anthropic LLM interface
│   └── storage/                    # SQLite DB, raw cache, vector store, export
└── tests/
    ├── unit/                       # mocked, no network
    └── integration/                # requires network and API key
```
