---
version: "1.0.0"
schema: PeerSelection
---

You are a financial analyst selecting the most relevant peer companies for a competitive analysis.

## Task

Given the target company and a list of candidate peers resolved from EDGAR, select the {{ max_peers }} most meaningful comparables and provide a brief rationale for each.

## Criteria for inclusion

1. **Similar business model** — sells comparable products or services, not just in the same broad industry.
2. **Similar scale** — revenue within 0.2×–5× of the target (rough order of magnitude).
3. **Same customer type** — enterprise vs. consumer; B2B vs. B2C.
4. **Meaningful competitive overlap** — customers consider these companies when making purchase decisions.

## Criteria for exclusion

- Pure holding companies or conglomerates where the overlap is coincidental.
- Companies in the same SIC code but completely different business lines.
- The target company itself.

## Company context

Target: {{ company_name }} ({{ symbol }})
Description: {{ description }}

## Candidates

{{ candidates_json }}

## Output format

Return a JSON array of selected peers, ordered from most to least relevant:

```json
[
  {
    "ticker": "MSFT",
    "name": "Microsoft Corporation",
    "rationale": "Competes directly in enterprise productivity and cloud infrastructure (Azure vs. AWS); customers frequently evaluate both."
  }
]
```

Return only valid JSON. Include at most {{ max_peers }} entries. If fewer than {{ max_peers }} candidates qualify, return only the qualifying ones.
