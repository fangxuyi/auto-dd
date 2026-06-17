"""LLM synthesis for value chain — chokepoint enrichment and executive summary."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from company_research.models.identity import CompanyIdentity
from company_research.models.value_chain import (
    ChokepointAssessment,
    CompanyRelationship,
    ProfitPoolAssessment,
    ValueChainGraph,
)

log = logging.getLogger(__name__)
_MODEL = "claude-sonnet-4-6"
_PROMPTS_DIR = Path(__file__).resolve().parents[4] / "prompts"


def _load_prompt(name: str) -> str:
    path = _PROMPTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        end = text.index("---", 3)
        return text[end + 3:].strip()
    return text.strip()


def enrich_chokepoints_llm(
    chokepoints: list[ChokepointAssessment],
    relationships: list[CompanyRelationship],
    company: CompanyIdentity,
    max_enrich: int = 5,
) -> list[ChokepointAssessment]:
    """
    Call LLM to fill in failure_mechanism, financial_effect,
    early_warning_indicators, and mitigation for each chokepoint.
    Returns the same list with fields populated. Fails gracefully per-item.
    """
    if not chokepoints:
        return chokepoints

    import anthropic

    rel_summaries = [
        f"- {r.relationship_type}: {r.product_or_service or 'unknown product'} "
        f"(confidence: {r.confidence}, materiality: {r.materiality})"
        for r in relationships[:20]
    ]
    rel_context = "\n".join(rel_summaries) or "No confirmed relationships."

    try:
        prompt_template = _load_prompt("vc_chokepoint_enrich.md")
    except FileNotFoundError:
        log.warning("vc_chokepoint_enrich.md not found — using inline prompt")
        prompt_template = (
            "You are a supply-chain risk analyst. For each chokepoint below, provide:\n"
            "- failure_mechanism: how the disruption would propagate\n"
            "- financial_effect: estimated revenue/margin impact\n"
            "- early_warning_indicators: 2-3 observable signals\n"
            "- mitigation: what the company could do\n\n"
            "Company: {company_name} ({symbol})\n"
            "Relationships:\n{rel_context}\n\n"
            "Chokepoints (JSON array):\n{chokepoints_json}\n\n"
            "Return a JSON array with the same length, each object having keys:\n"
            "chokepoint_id, failure_mechanism, financial_effect, "
            "early_warning_indicators (list), mitigation"
        )

    client = anthropic.Anthropic()
    enriched: list[ChokepointAssessment] = []

    for cp in chokepoints[:max_enrich]:
        prompt = prompt_template.format(
            company_name=company.issuer_name,
            symbol=company.symbol,
            rel_context=rel_context,
            chokepoints_json=json.dumps([{
                "chokepoint_id": cp.chokepoint_id,
                "chokepoint": cp.chokepoint,
                "confidence": cp.confidence,
            }], indent=2),
        )
        try:
            msg = client.messages.create(
                model=_MODEL,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            text = msg.content[0].text.strip()
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                data = json.loads(text[start:end])
                if data and isinstance(data, list):
                    d = data[0]
                    cp.failure_mechanism = d.get("failure_mechanism", "")
                    cp.financial_effect = d.get("financial_effect")
                    cp.early_warning_indicators = d.get("early_warning_indicators", [])
                    cp.mitigation = d.get("mitigation")
        except Exception as exc:
            log.warning("LLM chokepoint enrichment failed for %s: %s", cp.chokepoint_id[:8], exc)
        enriched.append(cp)

    enriched.extend(chokepoints[max_enrich:])
    return enriched


def synthesize_vc_narrative(
    symbol: str,
    company_name: str,
    graph: ValueChainGraph,
    profit_pools: list[ProfitPoolAssessment],
    chokepoints: list[ChokepointAssessment],
) -> str:
    """
    LLM-written executive summary for the value chain report.
    Returns a markdown string. Falls back to a boilerplate if the LLM call fails.
    """
    import anthropic

    confirmed = graph.confirmed_edges
    node_names = [n.entity_name for n in graph.nodes[:10]]

    pp_lines = [
        f"  - {pp.layer_name}: gross margin {pp.gross_margin_range or 'unknown'}, "
        f"pricing power {pp.pricing_power}"
        for pp in profit_pools
    ]
    cp_lines = [f"  - {cp.chokepoint}" for cp in chokepoints[:3]]

    try:
        prompt_template = _load_prompt("vc_executive_summary.md")
    except FileNotFoundError:
        prompt_template = (
            "You are a financial research analyst. Write a 3–4 sentence executive summary\n"
            "of {company_name}'s ({symbol}) value chain position based on the data below.\n"
            "Focus on: where value is concentrated, key dependencies, and main risks.\n"
            "Write in third person. Do not introduce facts not given.\n\n"
            "Confirmed relationships: {confirmed_count}\n"
            "Key entities: {entities}\n"
            "Profit pools:\n{profit_pools}\n"
            "Chokepoints:\n{chokepoints}"
        )

    prompt = prompt_template.format(
        company_name=company_name,
        symbol=symbol,
        confirmed_count=len(confirmed),
        entities=", ".join(node_names) or "none identified",
        profit_pools="\n".join(pp_lines) or "  none",
        chokepoints="\n".join(cp_lines) or "  none identified",
    )

    try:
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=_MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as exc:
        log.warning("LLM VC narrative synthesis failed: %s", exc)
        cp_text = (
            "Key chokepoints identified: "
            + "; ".join(c.chokepoint for c in chokepoints[:2])
            + "."
            if chokepoints else ""
        )
        return (
            f"{company_name} ({symbol}) has {len(confirmed)} confirmed value chain relationships "
            f"spanning {len(graph.nodes)} entities. {cp_text}"
        ).strip()
