"""Industry template loader — reads YAML templates from config/value_chain_templates/."""
from __future__ import annotations

from pathlib import Path

import yaml

_TEMPLATES_DIR = Path(__file__).parent.parent.parent.parent / "config" / "value_chain_templates"

_INDUSTRY_KEYWORDS: dict[str, list[str]] = {
    "software_cloud": [
        "software", "saas", "cloud", "platform", "data", "analytics", "cybersecurity",
        "enterprise", "fintech", "edtech", "martech", "devtools",
    ],
    "semiconductors": [
        "semiconductor", "chip", "fab", "foundry", "wafer", "eda", "ip licensing",
        "integrated circuit", "processor", "memory", "logic",
    ],
    "consumer_products": [
        "consumer", "brand", "retail", "cpg", "food", "beverage", "apparel",
        "personal care", "household", "e-commerce",
    ],
    "industrials": [
        "industrial", "manufacturing", "equipment", "machinery", "aerospace", "defense",
        "automation", "robotics", "energy transition", "construction",
    ],
    "healthcare": [
        "pharma", "pharmaceutical", "biotech", "medtech", "medical device", "diagnostic",
        "health", "therapeutic", "clinical", "drug",
    ],
    "financial_services": [
        "bank", "financial", "insurance", "asset management", "fintech", "payments",
        "brokerage", "exchange", "capital markets", "lending",
    ],
    "energy_commodities": [
        "oil", "gas", "energy", "power", "utility", "mining", "commodity",
        "renewable", "solar", "wind", "lng", "refining", "pipeline",
    ],
}


def load_template(name: str) -> dict:
    """Load a YAML template by name (without .yaml extension)."""
    path = _TEMPLATES_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No value chain template '{name}' at {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def list_templates() -> list[str]:
    """Return names of all available templates."""
    return sorted(p.stem for p in _TEMPLATES_DIR.glob("*.yaml"))


def infer_template(sic_code: str | None, issuer_name: str, description: str = "") -> str:
    """
    Guess the best-fit template from issuer name and description text.
    Returns a template name string, defaulting to 'software_cloud'.
    """
    text = f"{issuer_name} {description}".lower()
    for template_name, keywords in _INDUSTRY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return template_name
    return "software_cloud"


def get_suggested_queries(template: dict, company_name: str) -> dict[str, list[str]]:
    """Substitute company name into template's suggested query strings."""
    raw = template.get("suggested_queries", {})
    result: dict[str, list[str]] = {}
    for direction, queries in raw.items():
        result[direction] = [q.replace("{company}", company_name) for q in queries]
    return result
