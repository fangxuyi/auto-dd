---
version: "1.0.0"
schema: ChokepointAssessment
---

You are a supply-chain risk analyst. For each chokepoint provided, analyse the failure mode and financial consequences based on the relationship context.

## Rules

- Base your analysis only on the relationship data provided. Do not introduce external knowledge.
- failure_mechanism: describe how the disruption propagates operationally (e.g. "production halt within 4–6 weeks if sole-source supplier halts shipment").
- financial_effect: quantify if possible using relationship materiality; otherwise describe qualitatively.
- early_warning_indicators: 2–3 specific, observable leading indicators (news, filings, operational signals).
- mitigation: what the company could do to reduce exposure.

## Company: {company_name} ({symbol})

## Confirmed relationships
{rel_context}

## Chokepoints to enrich
{chokepoints_json}

Return a JSON array (same length as input) with keys: chokepoint_id, failure_mechanism, financial_effect, early_warning_indicators (list of strings), mitigation.
