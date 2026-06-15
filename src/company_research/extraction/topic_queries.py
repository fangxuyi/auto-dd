from __future__ import annotations

# Natural-language queries used to retrieve relevant chunks from the vector store
# for each report section. Richer queries = better retrieval precision.
TOPIC_QUERIES: dict[str, str] = {
    "business_model": (
        "business model how company makes money revenue streams pricing strategy "
        "products and services description business segments operating model"
    ),
    "product": (
        "core product product description features capabilities technology platform "
        "what the company sells product portfolio product lines key offerings"
    ),
    "customers": (
        "customer segments customer base enterprise customers SMB consumer customers "
        "customer concentration top customers revenue by customer type customer mix "
        "customer count accounts"
    ),
    "market": (
        "total addressable market TAM SAM market size industry size market growth "
        "addressable market market opportunity market share competitive market dynamics"
    ),
    "competition": (
        "competitive landscape competitors market share competitive position "
        "competitive advantages differentiation win rates competitive threats "
        "industry competition alternatives substitutes"
    ),
    "revenue": (
        "revenue growth revenue breakdown revenue by segment subscription revenue "
        "recurring revenue ARR NRR net revenue retention pricing power price increases "
        "revenue recognition deferred revenue backlog"
    ),
    "financials": (
        "gross margin operating margin EBITDA free cash flow cash generation "
        "working capital capital expenditure return on invested capital dilution "
        "stock based compensation earnings operating leverage profitability"
    ),
    "management": (
        "management team CEO CFO executive leadership management track record "
        "capital allocation management history executive compensation guidance "
        "management commentary strategic priorities"
    ),
    "risk": (
        "risk factors key risks regulatory risk competitive risk technology risk "
        "customer concentration risk supply chain risk macroeconomic risk "
        "material risk operational risk cybersecurity risk"
    ),
    "governance": (
        "corporate governance board of directors ownership structure dual class shares "
        "executive compensation insider ownership shareholder rights proxy statement "
        "related party transactions board independence"
    ),
}
