"""Incremental update pipeline — fetches new sources and diffs against a prior run."""
from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path

from company_research.config import settings
from company_research.models.diff import (
    ConclusionChange,
    FactChange,
    MetricChange,
    MonitoringDashboard,
    MonitoringIndicator,
    ResearchDiff,
)
from company_research.models.identity import ResearchRun
from company_research.storage.database import Database

log = logging.getLogger(__name__)


# ── diff helpers ─────────────────────────────────────────────────────────────


def _diff_metrics(
    prior_metrics: list[dict], new_metrics: list[dict]
) -> list[MetricChange]:
    """Compare metric lists by (name, period); return changed or new entries."""
    prior_idx: dict[tuple[str, str], dict] = {
        (m["name"], m["period"]): m for m in prior_metrics
    }
    new_idx: dict[tuple[str, str], dict] = {
        (m["name"], m["period"]): m for m in new_metrics
    }

    changes: list[MetricChange] = []
    all_keys = set(prior_idx) | set(new_idx)

    for key in sorted(all_keys):
        prior = prior_idx.get(key)
        new = new_idx.get(key)
        if prior is None and new is not None:
            changes.append(
                MetricChange(
                    name=new["name"],
                    period=new["period"],
                    unit=new.get("unit", ""),
                    prior_value=None,
                    new_value=new["value"],
                )
            )
        elif prior is not None and new is not None:
            pv, nv = float(prior["value"]), float(new["value"])
            if abs(pv - nv) > 1e-9:
                chg = (nv - pv) / abs(pv) if abs(pv) > 1e-9 else None
                changes.append(
                    MetricChange(
                        name=new["name"],
                        period=new["period"],
                        unit=new.get("unit", ""),
                        prior_value=pv,
                        new_value=nv,
                        change_pct=round(chg * 100, 2) if chg is not None else None,
                    )
                )
    return changes


def _diff_conclusions(
    prior_conclusions: list[dict], new_conclusions: list[dict]
) -> list[ConclusionChange]:
    prior_idx = {c["section"]: c for c in prior_conclusions}
    new_idx = {c["section"]: c for c in new_conclusions}

    changes: list[ConclusionChange] = []
    for section, new_c in new_idx.items():
        prior_c = prior_idx.get(section)
        if prior_c is None:
            changes.append(
                ConclusionChange(
                    section=section,
                    change_type="new",
                    new_conclusion=new_c["conclusion"],
                    new_confidence=new_c["confidence"],
                )
            )
        elif prior_c["conclusion"] != new_c["conclusion"]:
            changes.append(
                ConclusionChange(
                    section=section,
                    change_type="changed",
                    prior_conclusion=prior_c["conclusion"],
                    new_conclusion=new_c["conclusion"],
                    prior_confidence=prior_c["confidence"],
                    new_confidence=new_c["confidence"],
                )
            )
        else:
            changes.append(
                ConclusionChange(
                    section=section,
                    change_type="same",
                    prior_conclusion=prior_c["conclusion"],
                    new_conclusion=new_c["conclusion"],
                    prior_confidence=prior_c["confidence"],
                    new_confidence=new_c["confidence"],
                )
            )
    return changes


def _diff_facts(
    prior_facts: list[dict], new_facts: list[dict]
) -> list[FactChange]:
    """Detect new top-level claims per topic (claim-level diffing by text)."""
    prior_by_topic: dict[str, set[str]] = {}
    for f in prior_facts:
        prior_by_topic.setdefault(f["topic"], set()).add(f["claim"])

    changes: list[FactChange] = []
    for f in new_facts:
        topic_claims = prior_by_topic.get(f["topic"], set())
        if f["claim"] not in topic_claims:
            changes.append(
                FactChange(
                    topic=f["topic"],
                    change_type="new",
                    new_claim=f["claim"],
                    source_id=f.get("source_id"),
                )
            )
    return changes


# ── monitoring dashboard ──────────────────────────────────────────────────────


def build_monitoring_dashboard(
    run_id: str, symbol: str, as_of: date, db: Database
) -> MonitoringDashboard:
    conclusions = db.get_conclusions(run_id)
    indicators: list[MonitoringIndicator] = []
    for c in conclusions:
        for ind in c.get("monitoring_indicators", []):
            if ind:
                indicators.append(
                    MonitoringIndicator(
                        section=c["section"],
                        indicator=ind,
                        run_id=run_id,
                        symbol=symbol,
                        as_of_date=as_of,
                    )
                )
    return MonitoringDashboard(
        symbol=symbol,
        as_of_date=as_of,
        run_id=run_id,
        indicators=indicators,
    )


# ── incremental update ────────────────────────────────────────────────────────


def update(
    symbol: str,
    depth: str,
    as_of: date,
    lookback_years: int,
    output_root: Path,
    dry_run: bool = False,
    rag_top_k: int | None = None,
) -> tuple[ResearchRun, ResearchDiff]:
    """
    Run an incremental update for `symbol`:
    1. Locate the most recent prior run in the DB.
    2. Run the full pipeline with `since=prior_date` so adapters skip already-seen sources.
    3. Diff new run against prior run.
    4. Return the new ResearchRun and the ResearchDiff.

    If no prior run exists, delegates to the full `analyze()` pipeline without diff.
    """
    db_path = output_root / "research.db"
    db = Database(db_path)

    prior_run = db.get_latest_run(symbol)
    if prior_run is None:
        log.info("No prior run found for %s — running full analysis.", symbol)
        from company_research.pipeline import analyze
        new_run = analyze(
            symbol=symbol,
            depth=depth,
            as_of=as_of,
            lookback_years=lookback_years,
            output_root=output_root,
            dry_run=dry_run,
            rag_top_k=rag_top_k,
        )
        # Build an empty diff (no prior to compare against)
        diff = ResearchDiff(
            symbol=symbol.upper(),
            prior_run_id=new_run.run_id,
            new_run_id=new_run.run_id,
            prior_date=as_of,
            new_date=as_of,
        )
        return new_run, diff

    prior_date_str = prior_run["as_of_date"]
    log.info(
        "Prior run found: run_id=%s as_of=%s — running incremental update.",
        prior_run["run_id"], prior_date_str,
    )

    # Run the full pipeline (it will re-use cached sources for already-fetched docs)
    from company_research.pipeline import analyze
    new_run = analyze(
        symbol=symbol,
        depth=depth,
        as_of=as_of,
        lookback_years=lookback_years,
        output_root=output_root,
        dry_run=dry_run,
        rag_top_k=rag_top_k,
    )

    # Build the diff
    prior_metrics = db.get_metrics(prior_run["run_id"])
    new_metrics = db.get_metrics(new_run.run_id)
    prior_facts = db.get_facts(prior_run["run_id"])
    new_facts = db.get_facts(new_run.run_id)
    prior_conclusions = db.get_conclusions(prior_run["run_id"])
    new_conclusions = db.get_conclusions(new_run.run_id)

    new_sources = db.get_sources_since(symbol, prior_date_str)

    from datetime import date as _date
    diff = ResearchDiff(
        symbol=symbol.upper(),
        prior_run_id=prior_run["run_id"],
        new_run_id=new_run.run_id,
        prior_date=_date.fromisoformat(prior_date_str),
        new_date=as_of,
        new_sources_count=len(new_sources),
        changed_metrics=_diff_metrics(prior_metrics, new_metrics),
        changed_conclusions=_diff_conclusions(prior_conclusions, new_conclusions),
        new_facts=_diff_facts(prior_facts, new_facts),
    )
    return new_run, diff
