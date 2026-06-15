from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_TEMPLATE_PATH = (
    Path(__file__).parent.parent.parent.parent
    / "guidelines"
    / "company_product_business_fundamentals_analysis_template_v2.md"
)

# Maps SECTION_TOPICS keys → template heading keywords used to locate the section
_SECTION_HEADING_KEYWORDS: dict[str, list[str]] = {
    "company_snapshot": ["Company Snapshot"],
    "core_product": ["Customer Problem and Product Value Proposition"],
    "product_market_fit": ["Product Quality and Product-Market Fit"],
    "customer_base": ["Customer Base and Customer Economics"],
    "market_structure": ["Market Structure and Addressable Market"],
    "competitive_landscape": ["Competitive Landscape"],
    "competitive_advantage": ["Competitive Advantage and Moat"],
    "revenue_model": ["Revenue Model and Pricing Power", "Unit Economics and Scalability"],
    "financial_quality": ["Financial Quality and Cash Conversion"],
    "management_governance": ["Management Quality", "Governance, Ownership"],
    "current_challenges": ["Current Challenges"],
    "key_risks": ["Risk Analysis"],
    "growth_opportunities": ["Growth Opportunities and Future Prospects"],
    "scenarios": ["Scenario Analysis"],
    "monitoring_dashboard": ["Ongoing Monitoring Dashboard"],
}


@lru_cache(maxsize=1)
def _load_template() -> str:
    try:
        return _TEMPLATE_PATH.read_text()
    except FileNotFoundError:
        return ""


def _extract_section_block(template: str, heading: str) -> str:
    """Extract the markdown block starting at `## N. <heading>` until the next `## `."""
    pattern = re.compile(
        rf"(##\s+\d+\.\s+{re.escape(heading)}.*?)(?=\n## |\Z)",
        re.DOTALL | re.IGNORECASE,
    )
    m = pattern.search(template)
    return m.group(1).strip() if m else ""


def get_section_guidance(section: str) -> str:
    """Return the template guidance text for a given section name.

    Returns an empty string if no mapping or the template file is missing.
    """
    keywords = _SECTION_HEADING_KEYWORDS.get(section, [])
    if not keywords:
        return ""

    template = _load_template()
    if not template:
        return ""

    blocks: list[str] = []
    for kw in keywords:
        block = _extract_section_block(template, kw)
        if block:
            blocks.append(block)

    return "\n\n".join(blocks)
