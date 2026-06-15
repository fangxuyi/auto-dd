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

    # conclusions → used by report generator
    conclusions = db.get_conclusions(run_id)
    (out_dir / "conclusions.json").write_text(
        json.dumps(conclusions, indent=2, default=str), encoding="utf-8"
    )


def export_qa(qa: QAResult, out_dir: Path) -> None:
    (out_dir / "qa_report.json").write_text(
        qa.model_dump_json(indent=2), encoding="utf-8"
    )
