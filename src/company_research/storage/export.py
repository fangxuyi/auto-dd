from __future__ import annotations

import csv
import json
from pathlib import Path

from company_research.models.qa import QAResult
from company_research.storage.database import Database


def export_run(run_id: str, db: Database, out_dir: Path) -> None:
    """Write all structured output files for a completed run."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # sources.json
    sources = db.get_sources(run_id)
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

    # peers.json — placeholder; peer selection added in M3
    (out_dir / "peers.json").write_text(
        json.dumps([], indent=2), encoding="utf-8"
    )


def export_qa(qa: QAResult, out_dir: Path) -> None:
    (out_dir / "qa_report.json").write_text(
        qa.model_dump_json(indent=2), encoding="utf-8"
    )
