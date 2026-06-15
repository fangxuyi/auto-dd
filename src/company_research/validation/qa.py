from __future__ import annotations

from datetime import datetime
from pathlib import Path

from company_research.models.qa import QAResult
from company_research.storage.database import Database


def run_qa(run_id: str, db: Database, out_dir: Path | None = None) -> QAResult:
    """Run QA gate checks for a completed research run."""
    checks: dict[str, bool] = {}
    critical: list[str] = []
    warnings: list[str] = []

    facts = db.get_facts(run_id)
    sources = db.get_sources(run_id)
    citations = db.get_citations(run_id)
    conclusions = db.get_conclusions(run_id)
    contradictions = db.get_contradictions(run_id)

    # 1. At least one source acquired
    checks["has_sources"] = len(sources) > 0
    if not checks["has_sources"]:
        critical.append("No sources were acquired for this run.")

    # 2. At least one fact extracted
    checks["has_facts"] = len(facts) > 0
    if not checks["has_facts"]:
        critical.append("No facts were extracted.")

    # 3. Every fact has period or no numeric value
    facts_missing_period = [
        f["fact_id"] for f in facts
        if f.get("value") and not f.get("period")
    ]
    checks["numeric_facts_have_period"] = len(facts_missing_period) == 0
    if facts_missing_period:
        critical.append(
            f"{len(facts_missing_period)} numeric facts are missing period: "
            + ", ".join(facts_missing_period[:3])
        )

    # 4. Every fact has unit if it has a numeric value
    facts_missing_unit = [
        f["fact_id"] for f in facts
        if f.get("value") and not f.get("unit")
    ]
    checks["numeric_facts_have_unit"] = len(facts_missing_unit) == 0
    if facts_missing_unit:
        critical.append(
            f"{len(facts_missing_unit)} numeric facts are missing unit: "
            + ", ".join(facts_missing_unit[:3])
        )

    # 5. No unresolved material contradictions hidden from report
    material_unresolved = [
        c for c in contradictions
        if c.get("severity") == "material" and not c.get("resolved")
    ]
    checks["no_hidden_material_contradictions"] = len(material_unresolved) == 0
    if material_unresolved:
        critical.append(
            f"{len(material_unresolved)} material contradictions are unresolved and must be disclosed."
        )

    # 6. Each conclusion references at least one fact
    conclusions_without_facts = [
        c["section"] for c in conclusions
        if not c.get("supporting_fact_ids")
    ]
    checks["conclusions_have_supporting_facts"] = len(conclusions_without_facts) == 0
    if conclusions_without_facts:
        warnings.append(
            f"Sections with no supporting facts: {', '.join(conclusions_without_facts)}"
        )

    # 7. Citations verified (warning only — not all may be verifiable)
    unverified = [c for c in citations if not c.get("verified")]
    checks["citations_verified"] = len(unverified) == 0
    if unverified:
        warnings.append(f"{len(unverified)} citations could not be verified.")

    # 8. TAM check — no unsupported market size claims
    tam_facts = [
        f for f in facts
        if f.get("topic") == "market"
        and f.get("fact_claim_or_inference") == "inference"
        and f.get("confidence") == "low"
    ]
    checks["no_unsupported_tam"] = len(tam_facts) == 0
    if tam_facts:
        warnings.append(
            f"{len(tam_facts)} low-confidence market-size inferences detected — verify sources."
        )

    # 9. report.md was produced
    if out_dir is not None:
        report_exists = (out_dir / "report.md").exists()
        checks["report_md_exists"] = report_exists
        if not report_exists:
            critical.append("report.md was not produced.")

        # 10. executive_summary.md was produced
        summary_exists = (out_dir / "executive_summary.md").exists()
        checks["executive_summary_exists"] = summary_exists
        if not summary_exists:
            critical.append("executive_summary.md was not produced.")

    # 11. Every profile section has at least one conclusion (warning only)
    conclusion_sections = {c["section"] for c in conclusions}
    if conclusions:
        checks["sections_have_conclusions"] = len(conclusion_sections) > 0
    else:
        checks["sections_have_conclusions"] = False
        warnings.append("No section conclusions were generated.")

    passed = len(critical) == 0

    return QAResult(
        run_id=run_id,
        passed=passed,
        critical_failures=critical,
        warnings=warnings,
        checks=checks,
        timestamp=datetime.utcnow(),
    )
