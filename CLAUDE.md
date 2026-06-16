# CLAUDE.md — auto-dd

## Project purpose

Reproducible CLI research pipeline that produces cited product-and-business fundamentals reports for public companies, following `guidelines/company_product_business_fundamentals_analysis_template_v2.md`.

## Permanent rules

- Read `guidelines/company_product_business_fundamentals_and_value_chain_analysis_template_v3.md` before changing any research logic. The v3 template supersedes v2 and adds Part IX (agent spec) and Part X (value chain).
- Never generate a fact, quotation, number, or citation not present in the stored evidence. The evidence store is the system of record, not the LLM.
- Prefer primary sources (SEC filings, regulator databases) over secondary sources.
- Keep retrieval, extraction, analysis, and writing strictly separate pipeline stages.
- Use typed Pydantic schemas at every stage boundary.
- Add tests for every parser or normalization change.
- Never silently ignore errors — raise or log with full context.
- Preserve raw sources and audit trails (content-addressed cache).
- Do not weaken QA gates to make a run pass.
- Do not introduce a paid service as a mandatory dependency.
- Never commit credentials, cookies, tokens, API keys, or copyrighted paid reports.
- Ask before changing source-access strategy or storage format.
- Keep prompts versioned in `prompts/` — never inline prompts in code.
- Record model ID, prompt version, code commit, and config hash for every run.

## Architecture

```
CLI → Pipeline orchestrator
  1. Entity resolver    → CompanyIdentity (deterministic)
  2. Source adapters    → SourceRecord[]  (deterministic)
  3. Raw cache          → RawDocument[]   (deterministic)
  4. Parsers            → NormalizedDocument[] (deterministic)
  5. Fact extractor     → EvidenceFact[]  (LLM)
  6. Fact validator     → validated facts (deterministic)
  7. Contradiction det. → Contradiction[] (LLM)
  8. Section analyzers  → SectionConclusion[] (LLM)
  9. Report generator   → report.md       (LLM, reads evidence store only)
  10. QA runner         → QAResult        (deterministic)
```

## LLM boundary

Use code for: filing retrieval, parsing, date normalization, unit conversion, table extraction, deduplication, metric calculations, citation indexing, schema validation, caching, change detection, QA checks.

Use LLM for: product interpretation, customer-problem analysis, competitive reasoning, moat assessment, management-candor evaluation, contradiction interpretation, risk formulation, scenario narratives.

## Key invariants

- Report generator never browses the web — reads only from the SQLite evidence store.
- Every fact must carry: source_id, location, period, unit, extraction_method, confidence.
- LLM structured output: validate against schema → retry with errors → repair prompt → fail (never accept malformed).
- All storage writes are idempotent (content-hash deduplication).

## Running

```bash
pip install -e ".[dev]"
export ANTHROPIC_API_KEY=sk-...
company-research analyze AAPL --depth standard --as-of 2026-06-15 --output ./research
pytest tests/unit/          # no live data
pytest tests/ -m live       # requires network
```
