# Value Chain and Public-Company Mapping Specification

## 45. Purpose

This module identifies the target company's upstream inputs, downstream routes to market, end customers, complementors, substitutes, bottlenecks, bargaining power, profit pools, and relevant public companies.

The goal is an evidence-supported economic map, not the longest possible company list.

## 46. Core Definitions

**Upstream:** Providers of raw materials, components, manufacturing, cloud infrastructure, data, software, logistics, equipment, intellectual property, energy, or specialized services used by the target.

**Company layer:** Activities performed by the target, including design, procurement, production, hosting, sales, support, billing, and monetization.

**Downstream:** Distributors, resellers, integrators, marketplaces, retailers, OEM partners, channel partners, enterprise customers, and end-market industries.

**Complementors:** Products or services that increase the target product's usefulness or adoption.

**Substitutes:** Alternative methods of solving the same customer problem.

Competitors must not automatically be classified as downstream, and suppliers must not automatically be called strategic partners.

## 47. Required Outputs

Every value-chain report must contain:

1. Narrative value-chain overview
2. Layer-by-layer map
3. Internal versus outsourced activities
4. Upstream public-company table
5. Downstream public-company table
6. Complementors and substitutes
7. Concentration and dependency analysis
8. Bargaining-power analysis
9. Profit-pool analysis
10. Bottlenecks and chokepoints
11. Relationship-confidence assessment
12. Missing evidence
13. Monitoring indicators
14. Machine-readable relationship graph

## 48. Value-Chain Construction Procedure

### Step 1: Define the delivered product

Record:

- Product or service
- Economic buyer
- End user
- Unit of delivery
- Revenue-generating event

### Step 2: Decompose activities

Identify which activities are internal or outsourced:

- Research and design
- Procurement
- Manufacturing
- Hosting
- Fulfillment
- Distribution
- Installation
- Servicing
- Billing

### Step 3: Map upstream categories

For each input, assess:

- Criticality
- Spend importance
- Supplier concentration
- Substitutes
- Switching or qualification time
- Geography
- Contract structure
- Pricing mechanism

### Step 4: Map downstream routes

Assess:

- Direct versus indirect sales
- Channel ownership
- Customer ownership
- Revenue sharing
- Exclusivity
- Integration depth
- Bargaining power
- Disintermediation risk

### Step 5: Map end-market exposure

Classify demand by customer type, industry, geography, use case, regulation, and cyclicality.

## 49. Public-Company Inclusion Standard

Include a company only when:

1. Its public listing is verified; and
2. Its value-chain role is supported by evidence; or
3. It is explicitly labeled as a category participant rather than a confirmed relationship.

Required status:

| Status | Meaning |
|---|---|
| Confirmed direct relationship | Named supplier, customer, distributor, partner, or integrator |
| Confirmed category participant | Operates in the relevant layer, but no direct relationship is established |
| Inferred likely relationship | Indirect evidence suggests a relationship |
| Historical relationship | Previously existed but may not be current |
| Unverified candidate | Research lead only; excluded from headline conclusions |
| Contradicted | Evidence conflicts with or disproves the proposed relationship |

Never state that a company supplies, buys from, or partners with the target without direct evidence.

## 50. Standard Relationship Types

```yaml
SUPPLIES
CONTRACT_MANUFACTURES_FOR
HOSTS
PROVIDES_DATA_TO
LICENSES_IP_TO
DISTRIBUTES
RESELLS
INTEGRATES
MARKETPLACE_FOR
LOGISTICS_PROVIDER_TO
PAYMENT_PROVIDER_TO
CUSTOMER_OF
OEM_CUSTOMER_OF
CHANNEL_PARTNER_OF
COMPLEMENTS
SUBSTITUTES_FOR
COMPETES_WITH
INVESTS_IN
JOINT_VENTURE_WITH
HISTORICAL_RELATIONSHIP
CATEGORY_PARTICIPANT
```

Edges must be directional and stored using one canonical direction.

## 51. Relationship Evidence Schema

```yaml
relationship_id:
source_company_id:
target_company_id:
relationship_type:
value_chain_layer:
product_or_service:
geography:
start_date:
end_date:
current_status:
evidence_status:
confidence:
materiality:
exclusivity:
source_ids:
source_locations:
last_verified_date:
analyst_notes:
```

Evidence status:

```yaml
confirmed_primary
confirmed_secondary
inferred
historical
unverified
contradicted
```

Confidence:

- **High:** Direct disclosure, filing, contract, procurement record, or corroborated primary evidence
- **Medium:** Credible secondary evidence or multiple consistent indirect sources
- **Low:** Single indirect, old, or category-based evidence
- **Unknown:** Insufficient evidence

## 52. Public Listing and Parent Resolution

Resolve:

```yaml
legal_name:
common_name:
ticker:
exchange:
country:
security_type:
primary_listing:
adr_status:
operating_subsidiary:
ultimate_public_parent:
regulator_id:
isin:
active_listing:
as_of_date:
```

Rules:

- Map private subsidiaries and brands to the correct ultimate public parent.
- Preserve the operating entity involved in the relationship.
- Distinguish holding companies from operating companies.
- Distinguish ADRs from primary listings.
- Label delisted, acquired, and inactive securities.
- Do not merge similar company names.
- Mark unresolved ownership rather than guessing.

## 53. Relationship Source Hierarchy

1. Regulatory filings
2. Contracts, exhibits, tenders, and procurement awards
3. Joint official press releases
4. Named customer or supplier case studies
5. Official partner directories
6. Certification and compatibility directories
7. Government trade and procurement databases
8. Earnings calls and investor presentations
9. Credible trade publications
10. General media
11. Job postings and technical implementation evidence
12. Social media and forums for lead generation only

A customer logo alone is not sufficient proof of a current, material commercial relationship.

## 54. Discovery and Reverse Verification

Search both directions.

Target-first examples:

```text
"[Company]" supplier
"[Company]" customer
"[Company]" distributor
"[Company]" reseller
"[Company]" contract manufacturing
"[Company]" cloud provider
"[Company]" implementation partner
site:sec.gov "[Company]" supplier
site:sec.gov "[Company]" customer
```

Counterparty-first examples:

```text
"[Candidate]" "[Target]"
"[Candidate]" supplies "[Target]"
"[Candidate]" customer "[Target]"
```

High confidence requires a reverse-direction search.

## 55. Industry Templates

### Software and cloud

```text
Semiconductors / data centers / cloud
→ foundational software and data
→ application vendor
→ integrators and channels
→ enterprise customer
→ end user
```

### Semiconductors

```text
EDA / IP / equipment / materials
→ design
→ foundry
→ assembly and test
→ system OEM
→ distributor
→ end market
```

### Consumer products

```text
Raw materials
→ components and packaging
→ contract manufacturing
→ brand owner
→ distributor
→ retailer or marketplace
→ consumer
```

### Industrials

```text
Materials and components
→ equipment manufacturer
→ distributor or integrator
→ operator
→ aftermarket
→ end industry
```

### Healthcare

```text
Research tools / CRO / licensing
→ developer
→ trials
→ manufacturing
→ regulatory approval
→ providers / payers / distributors
→ patient
```

### Financial services

```text
Funding / infrastructure / data / technology
→ institution or platform
→ distribution channel
→ business or consumer
```

### Energy and commodities

```text
Resource ownership
→ extraction
→ processing
→ transportation
→ storage
→ distribution
→ end demand
```

Templates are hypotheses, not evidence.

## 56. Upstream Company Analysis

For every upstream public company assess:

- Input supplied
- Direct relationship evidence
- Target dependency
- Supplier dependency on target
- Substitutability
- Switching and qualification time
- Capacity constraints
- Geographic and political risk
- Price sensitivity
- Contract duration
- Single-source versus multi-source status
- Vertical-integration risk

| Company | Ticker | Layer | Input | Relationship status | Evidence | Target dependency | Supplier dependency | Confidence |
|---|---|---|---|---|---|---|---|---|

A supplier may be operationally critical to the target while the target is financially immaterial to the supplier.

## 57. Downstream Company Analysis

Assess:

- Channel or customer role
- Product purchased
- Revenue contribution when disclosed
- Customer concentration
- Contract length
- Renewal behavior
- Bargaining power
- Substitution or internalization risk
- Cross-selling potential
- End-market sensitivity
- Disintermediation risk

| Company | Ticker | Layer | Role | Relationship status | Evidence | Revenue relevance | Bargaining power | Confidence |
|---|---|---|---|---|---|---|---|---|

Do not treat every company in a target end market as a customer.

## 58. Dependency and Bargaining Power

Evaluate:

- Concentration
- Switching costs
- Alternatives
- Relative scale
- Information advantage
- Contract duration
- Pricing mechanism
- Vertical-integration threat
- Regulation
- Relationship-specific investment

| Score | Meaning |
|---:|---|
| 1 | Easily replaceable |
| 2 | Replaceable with modest cost or delay |
| 3 | Meaningful dependency; alternatives exist |
| 4 | High dependency; replacement is costly or slow |
| 5 | Critical bottleneck with few practical alternatives |

Always preserve written justification.

## 59. Profit Pools

Assess each layer using:

- Gross and operating margins
- Return on invested capital
- Capital intensity
- Concentration
- Switching costs
- IP control
- Capacity scarcity
- Pricing power
- Cyclicality
- Regulation

| Layer | Representative companies | Margin structure | Capital intensity | Concentration | Pricing power | Trend |
|---|---|---|---|---|---|---|

## 60. Bottlenecks and Chokepoints

Potential chokepoints include:

- Sole-source component
- Scarce manufacturing capacity
- Regulatory license
- Proprietary data
- Dominant platform or cloud provider
- Critical logistics route
- Specialized talent
- Distribution gatekeeper
- Concentrated customer budget
- Standard-setting body

```yaml
chokepoint:
owner_or_controller:
affected_product:
failure_mechanism:
replacement_time:
financial_effect:
early_warning_indicators:
mitigation:
confidence:
```

## 61. Structural Change

Assess:

- Vertical integration
- Outsourcing
- Reshoring or nearshoring
- Platform consolidation
- Direct distribution
- Open-source substitution
- Technology transitions
- Regulation
- Capacity expansion
- Commodity inflation
- Channel conflict
- Customer internalization

Distinguish current structure from likely future structure.

## 62. Graph Schema

Node:

```yaml
node_id:
entity_name:
entity_type:
public_status:
ticker:
exchange:
country:
industry:
value_chain_layers:
ultimate_public_parent:
```

Edge:

```yaml
edge_id:
source_node_id:
target_node_id:
relationship_type:
product_or_service:
status:
confidence:
materiality:
start_date:
end_date:
source_ids:
last_verified_date:
```

Required exports:

```text
value_chain_nodes.csv
value_chain_edges.csv
value_chain_graph.json
value_chain_relationships.json
```

Unverified candidates must not appear in the default graph.

## 63. Report Structure

```markdown
## Value Chain Executive Summary
## 1. Product and Economic Unit
## 2. End-to-End Value Chain
## 3. Internal versus Outsourced Activities
## 4. Critical Upstream Inputs
## 5. Upstream Public Companies
## 6. Routes to Market
## 7. Downstream Public Companies
## 8. Complementors and Substitutes
## 9. Concentration
## 10. Bargaining Power
## 11. Profit Pools
## 12. Bottlenecks
## 13. Structural Changes
## 14. Risks and Opportunities
## 15. Relationship Graph
## 16. Missing Evidence
## 17. Sources
```

## 64. QA Checklist

- [ ] Upstream and downstream are defined relative to the target.
- [ ] Confirmed relationships are separated from category participants.
- [ ] Every direct relationship has a citation.
- [ ] Reverse-direction verification was performed.
- [ ] Each public listing was resolved.
- [ ] Subsidiaries and public parents are distinguished.
- [ ] Historical relationships are not presented as current.
- [ ] Customers are not inferred from end-market membership.
- [ ] Suppliers are not inferred from technical compatibility.
- [ ] Relationship direction is correct.
- [ ] Materiality is not assumed.
- [ ] Profit pools and bottlenecks are analyzed.
- [ ] Unverified candidates are excluded from headline findings.
- [ ] Every graph edge resolves to evidence.
- [ ] Graph and narrative relationships are consistent.
