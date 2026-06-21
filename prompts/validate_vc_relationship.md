---
version: "1.0.0"
model: claude-haiku-4-5
max_tokens: 120
description: >
  Validate whether a reverse EDGAR lookup hit represents a genuine commercial
  supplier-customer relationship between two companies, or a false positive
  (competitor mention, litigation reference, unrelated industry, etc.).
---

You are validating a potential supply-chain relationship found by keyword search in an SEC filing.

Filer company: {{ filer_name }} ({{ filer_ticker }})
Target company: {{ target_name }}
Proposed relationship: {{ relationship_description }}

Filing context: {{ excerpt }}

Does this represent a genuine commercial relationship where {{ relationship_check }}?

Answer false if:
- The filer and target are direct competitors selling the same products
- The filer is in an unrelated industry with no plausible commercial link (e.g. banking, insurance, healthcare, real estate, utilities unrelated to the target's operations)
- The mention likely refers to litigation, patent disputes, or competitive analysis rather than a commercial transaction

Answer true only if there is a plausible commercial reason for one company to supply products or services to the other.

Respond with JSON only — no explanation outside the JSON:
{"is_genuine": true, "reason": "one sentence"}
or
{"is_genuine": false, "reason": "one sentence"}
