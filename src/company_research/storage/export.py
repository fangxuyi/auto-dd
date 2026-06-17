from __future__ import annotations

import csv
import json
from pathlib import Path

from company_research.models.diff import MonitoringDashboard, ResearchDiff
from company_research.models.qa import QAResult
from company_research.pipeline_flow import RunFlowRecorder
from company_research.storage.database import Database


def export_run(run_id: str, db: Database, out_dir: Path, symbol: str | None = None) -> None:
    """Write all structured output files for a completed run."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # sources.json — use all sources for the symbol so report_only runs include
    # 10-Ks indexed in a previous analyze run, not just this run's registrations.
    sources = db.get_sources_for_symbol(symbol) if symbol else db.get_sources(run_id)
    (out_dir / "sources.json").write_text(
        json.dumps(sources, indent=2, default=str), encoding="utf-8"
    )

    # evidence.jsonl
    facts = db.get_facts(run_id)
    with (out_dir / "evidence.jsonl").open("w", encoding="utf-8") as f:
        for fact in facts:
            f.write(json.dumps(fact, default=str) + "\n")

    # metrics.csv
    metrics = db.get_metrics(run_id)
    if metrics:
        fieldnames = list(metrics[0].keys())
        with (out_dir / "metrics.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(metrics)
    else:
        (out_dir / "metrics.csv").write_text("", encoding="utf-8")

    # contradictions.json
    contradictions = db.get_contradictions(run_id)
    (out_dir / "contradictions.json").write_text(
        json.dumps(contradictions, indent=2, default=str), encoding="utf-8"
    )

    # open_questions.json
    questions = db.get_questions(run_id)
    (out_dir / "open_questions.json").write_text(
        json.dumps(questions, indent=2, default=str), encoding="utf-8"
    )

    # conclusions.json
    conclusions = db.get_conclusions(run_id)
    (out_dir / "conclusions.json").write_text(
        json.dumps(conclusions, indent=2, default=str), encoding="utf-8"
    )

    # company_profile.json — stub populated from DB sources; extended in M3
    company_profile: dict = {}
    with db._conn() as conn:
        row = conn.execute(
            "SELECT * FROM companies WHERE symbol=(SELECT symbol FROM runs WHERE run_id=? LIMIT 1)",
            (run_id,),
        ).fetchone()
        if row:
            company_profile = dict(row)
    (out_dir / "company_profile.json").write_text(
        json.dumps(company_profile, indent=2, default=str), encoding="utf-8"
    )

    # peers.json
    peers = db.get_peers(run_id)
    (out_dir / "peers.json").write_text(
        json.dumps(peers, indent=2, default=str), encoding="utf-8"
    )


def export_qa(qa: QAResult, out_dir: Path) -> None:
    (out_dir / "qa_report.json").write_text(
        qa.model_dump_json(indent=2), encoding="utf-8"
    )


def export_flow(flow: RunFlowRecorder, out_dir: Path) -> None:
    (out_dir / "run_flow.json").write_text(
        json.dumps(flow.to_dict(), indent=2, default=str), encoding="utf-8"
    )


def export_diff(diff: ResearchDiff, out_dir: Path) -> None:
    """Write update_diff.json and update_diff.md to out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "update_diff.json").write_text(
        diff.model_dump_json(indent=2), encoding="utf-8"
    )

    lines: list[str] = [
        f"# Research Update — {diff.symbol}",
        "",
        f"**Prior run date:** {diff.prior_date}  ",
        f"**New run date:** {diff.new_date}  ",
        f"**New sources fetched:** {diff.new_sources_count}  ",
        "",
    ]

    # Changed metrics
    changed = [c for c in diff.changed_metrics if c.prior_value is not None]
    new_metrics = [c for c in diff.changed_metrics if c.prior_value is None]
    if changed:
        lines += ["## Metric changes", ""]
        lines += ["| Metric | Period | Prior | New | Change % |", "|---|---|---:|---:|---:|"]
        for m in changed:
            chg = f"{m.change_pct:+.1f}%" if m.change_pct is not None else "—"
            lines.append(
                f"| {m.name} | {m.period} | {m.prior_value:,.0f} | {m.new_value:,.0f} | {chg} |"
            )
        lines.append("")
    if new_metrics:
        lines += ["## New metrics", ""]
        for m in new_metrics:
            lines.append(f"- **{m.name}** ({m.period}): {m.new_value:,.0f} {m.unit}")
        lines.append("")

    # New facts
    if diff.new_facts:
        lines += [f"## New facts ({len(diff.new_facts)})", ""]
        for f in diff.new_facts[:20]:
            lines.append(f"- [{f.topic}] {f.new_claim}")
        if len(diff.new_facts) > 20:
            lines.append(f"- … and {len(diff.new_facts) - 20} more")
        lines.append("")

    # Conclusion changes
    changed_conclusions = [c for c in diff.changed_conclusions if c.change_type == "changed"]
    if changed_conclusions:
        lines += [f"## Changed conclusions ({len(changed_conclusions)})", ""]
        for c in changed_conclusions:
            lines += [
                f"### {c.section}",
                f"**Before ({c.prior_confidence}):** {c.prior_conclusion}  ",
                f"**After ({c.new_confidence}):** {c.new_conclusion}",
                "",
            ]

    # New risks
    if diff.new_risks:
        lines += ["## New risks", ""]
        for r in diff.new_risks:
            lines.append(f"- {r}")
        lines.append("")

    # Invalidated assumptions
    if diff.invalidated_assumptions:
        lines += ["## Invalidated assumptions", ""]
        for a in diff.invalidated_assumptions:
            lines.append(f"- {a}")
        lines.append("")

    if not (changed or new_metrics or diff.new_facts or changed_conclusions):
        lines.append("*No material changes detected in this update.*")

    (out_dir / "update_diff.md").write_text("\n".join(lines), encoding="utf-8")


def export_monitoring(dashboard: MonitoringDashboard, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "monitoring.json").write_text(
        dashboard.model_dump_json(indent=2), encoding="utf-8"
    )


def export_compare(compare_data: dict, out_dir: Path) -> None:
    """Write compare_<symbols>.json and compare_<symbols>.md."""
    out_dir.mkdir(parents=True, exist_ok=True)
    symbols_tag = "_".join(compare_data.get("symbols", []))

    (out_dir / f"compare_{symbols_tag}.json").write_text(
        json.dumps(compare_data, indent=2, default=str), encoding="utf-8"
    )

    lines: list[str] = [
        f"# Comparison: {' vs '.join(compare_data.get('symbols', []))}",
        "",
        f"**As of:** {compare_data.get('as_of_date')}",
        "",
    ]

    companies = compare_data.get("companies", {})
    syms = list(companies.keys())
    if not syms:
        (out_dir / f"compare_{symbols_tag}.md").write_text("\n".join(lines), encoding="utf-8")
        return

    from company_research.pipeline_compare import _COMPARE_METRICS

    header = "| Metric | Period | " + " | ".join(syms) + " |"
    divider = "|---|---|" + "|".join(["---:"] * len(syms)) + "|"
    lines += [header, divider]

    for metric_name in _COMPARE_METRICS:
        row_vals: list[str] = []
        period = "—"
        for sym in syms:
            m = companies[sym]["metrics"].get(metric_name)
            if m and m.get("value") is not None:
                row_vals.append(f"{m['value']:,.0f}")
                period = m.get("period", "—")
            else:
                row_vals.append("—")
        if any(v != "—" for v in row_vals):
            lines.append(f"| {metric_name} | {period} | " + " | ".join(row_vals) + " |")

    lines.append("")
    (out_dir / f"compare_{symbols_tag}.md").write_text("\n".join(lines), encoding="utf-8")
