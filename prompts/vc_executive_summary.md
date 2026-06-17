---
version: "1.0.0"
schema: str
---

You are a financial research analyst. Write a concise 3–4 sentence executive summary of {company_name}'s ({symbol}) value chain position. Focus on: where in the chain value is captured, key upstream dependencies, downstream reach, and primary risk concentration.

Write in third person. Do not introduce facts not present in the data below. If data is sparse, say so rather than speculating.

## Data

Confirmed value chain relationships: {confirmed_count}
Key entities identified: {entities}

Profit pools by layer:
{profit_pools}

Key chokepoints:
{chokepoints}
