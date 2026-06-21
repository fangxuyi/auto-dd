# auto-dd

**One command. 35 minutes. A fully cited due-diligence report on any public US company.**

auto-dd is an open-source CLI that pulls SEC filings, investor-relations pages, and web sources, extracts structured facts with full citations, and produces a research report you can actually trust — every claim traces back to a primary source.

---

## Quickstart

```bash
git clone https://github.com/fangxuyi/auto-dd.git
cd auto-dd
pip install -e ".[dev]"
export ANTHROPIC_API_KEY=sk-...
```

```bash
company-research research AAPL
```

That's it. The report opens in your browser when done.

---

## What you get

A self-contained HTML report with four tabs, generated in ~35 min for ~$3:

| Tab | What's inside |
|---|---|
| **Report** | 14-section research report — business model, product, customers, financials, competition, risks, scenarios — with inline citations and per-section confidence ratings |
| **Value Chain** | Interactive force-directed graph of upstream suppliers (amber) and downstream customers (teal), sourced from SEC filings. Hover any row to see the exact filing sentence. |
| **Sources** | Every document used: SEC filings, IR pages, product pages, web results — with reliability tier and date |
| **Ask** | Chat with the evidence — type any question, get a grounded answer with inline citations from the indexed sources |

A sample report for AAPL (`--depth standard`, 2026-06-21) is at [`AAPL_autodd_sample_report.html`](AAPL_autodd_sample_report.html).

---

## What the pipeline does

```
1. Resolve ticker → SEC EDGAR entity
2. Fetch sources: 10-K/10-Q filings, IR pages, product pages, web search, peer filings
3. Parse and index all documents into a local vector store
4. Extract structured facts from every section (cited to source IDs)
5. Detect contradictions across sources
6. Analyze each report section — conclusions, confidence, counterevidence
7. Synthesize the full report
8. Map upstream/downstream value chain from reverse EDGAR lookup
9. Export self-contained HTML + start local RAG server
```

Every fact carries: `source_id`, `location`, `period`, `unit`, `confidence`. The report generator reads only from the evidence store — it never browses the web.

---

## Requirements

- Python 3.11+
- `ANTHROPIC_API_KEY` in environment or `.env`
- No other paid services or API keys required (SEC EDGAR and DuckDuckGo are free)

---

## Depth options

```bash
company-research research AAPL                  # standard (default) — ~35 min, ~$3
company-research research AAPL --depth quick    # fewer sources — ~20 min, ~$2
company-research research AAPL --depth deep     # maximum sources — ~60 min, ~$6
```

| | `quick` | `standard` | `deep` |
|---|---|---|---|
| Web search | — | ✓ | ✓ |
| IR pages | ✓ | ✓ | ✓ |
| Product pages | — | ✓ | ✓ |
| Peer filings | 2 | 3 | 5 |
| Estimated cost | ~$2–3 | ~$3–4 | ~$5–8 |
| Estimated time | ~20 min | ~35 min | ~60 min |

---

## Options

```bash
company-research research AAPL --depth standard   # research depth
company-research research AAPL --no-value-chain   # skip value chain step
company-research research AAPL --no-serve         # generate HTML but don't start RAG server
company-research research AAPL --port 8080        # RAG server port (default: 7234)
company-research research AAPL --as-of 2026-01-01 # pin analysis date
company-research research AAPL --rag-top-k 20     # chunks retrieved per section
```

---

## Output files

All output is written to `./research/<SYMBOL>/<DATE>/`.

| File | Description |
|---|---|
| `report.html` | Self-contained 4-tab HTML report |
| `report.md` | Full research report in Markdown with citations |
| `value_chain_report.md` | Value chain narrative and relationship summary |
| `evidence.jsonl` | All extracted facts with source citations |
| `metrics.csv` | XBRL financial metrics (time-series) |
| `contradictions.json` | Cross-source contradictions detected |
| `sources.json` | All indexed documents |
| `qa_report.json` | QA gate results (pass/fail) |
| `run_flow.json` | Per-step timing and metrics |

---

## Individual commands

For running steps separately or re-generating output:

```bash
# Analyze only
company-research analyze AAPL --depth standard

# Value chain only (requires a prior analyze run)
company-research value-chain AAPL

# Convert an existing report.md to HTML
company-research to-html research/AAPL/2026-06-21/report.md

# Start the RAG Q&A server
company-research serve research/AAPL/2026-06-21/report.md --port 7234
```

---

## Cost breakdown

LLM calls use Claude via the Anthropic API. All sources (SEC EDGAR, DuckDuckGo, IR/product pages) are free.

**AAPL `--depth standard`** (measured, 2026-06-21):

| Step | Model | Time | Cost |
|---|---|---|---|
| Source fetch + parse | — | 0.7 min | — |
| Fact extraction (14 sections) | Haiku 4.5 | 10.6 min | ~$0.91 |
| Contradiction detection | Haiku 4.5 | 0.2 min | ~$0.15 |
| Section analysis (14 sections) | Sonnet 4.6 | 19.9 min | ~$0.86 |
| Report synthesis | Sonnet 4.6 | 4.0 min | ~$0.21 |
| Value chain extraction | Haiku 4.5 | — | ~$0.006 |
| **Total** | | **~35 min** | **~$3** |

Structured extraction uses Haiku 4.5; reasoning and synthesis use Sonnet 4.6. Both models are configurable via environment variables (`COMPANY_RESEARCH_EXTRACTION_MODEL`, `COMPANY_RESEARCH_MODEL`).

---

## Development

```bash
pytest tests/unit/     # unit tests — no network, no API key
pytest tests/ -m live  # integration tests — requires network and key
ruff check src/ tests/
mypy src/
```

---

## Architecture

```
CLI (click) — company-research research SYMBOL
└── Pipeline orchestrator
    ├── 1.   EntityResolver      → ticker → SEC EDGAR identity
    ├── 1b.  External adapters   → IR pages, product pages, web search
    ├── 1c.  PeerSelector        → peer company list
    ├── 2.   EdgarAdapter        → 10-K, 10-Q filings
    ├── 3-4. RawCache + Parsers  → HTML / PDF / XBRL / text
    ├── 5.   XBRLExtractor       → financial metrics (time-series)
    ├── 6.   FactExtractor       → EvidenceFact[] per section  [Haiku 4.5]
    ├── 7.   ContradictionDetector                              [Haiku 4.5]
    ├── 8.   CitationResolver    → verified source links
    ├── 9.   SectionAnalyzer     → conclusions + confidence    [Sonnet 4.6]
    ├── 10.  ReportGenerator     → report.md                   [Sonnet 4.6]
    ├── 11.  QARunner            → pass/fail gates
    └── 12.  Exporter            → report.html, sources.json, …

Value chain pipeline
    ├── Forward EDGAR discovery  → target's own filings
    ├── Reverse EDGAR lookup     → third-party filings that name the target
    ├── Entity resolution        → EDGAR-verified tickers
    ├── Product/service labels   → 3–7 word label per edge   [Haiku 4.5]
    └── Graph export             → value_chain_graph.json (embedded in HTML)
```

### Source reliability tiers

| Tier | Type | Examples |
|---|---|---|
| 1 | SEC regulatory filings | 10-K, 10-Q |
| 2 | Company operational pages | Product pages, pricing |
| 4 | Third-party analysis | Research, analyst summaries |
| 5 | Company IR communications | IR site, press releases |
| 6 | General web media | News articles |

---

## Project structure

```
auto-dd/
├── config/                         # depth profiles, source priorities
├── guidelines/                     # analysis template
├── prompts/                        # versioned LLM prompts
├── src/company_research/
│   ├── cli.py                      # CLI entrypoint
│   ├── pipeline.py                 # main orchestrator
│   ├── pipeline_value_chain.py     # value chain orchestrator
│   ├── config.py                   # settings + profile loader
│   ├── models/                     # Pydantic schemas
│   ├── sources/                    # EDGAR, web search, IR, product, peer adapters
│   ├── parsing/                    # HTML, PDF, XBRL, text parsers
│   ├── extraction/                 # fact extractor, XBRL extractor
│   ├── analysis/                   # section analyzer, contradiction detector
│   ├── reporting/                  # report generator, HTML export, RAG server
│   ├── validation/                 # QA gates, citation resolver
│   ├── llm/                        # Anthropic provider + retry logic
│   └── storage/                    # SQLite, raw cache, ChromaDB vector store
└── tests/
    ├── unit/                       # no network required
    └── integration/                # requires network + API key
```
