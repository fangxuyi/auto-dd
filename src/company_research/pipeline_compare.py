"""Side-by-side comparison of two or more company research runs."""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

# Key XBRL metrics to pull for comparison (name patterns matched against DB metric names)
_COMPARE_METRICS = [
    "Revenues",
    "GrossProfit",
    "OperatingIncomeLoss",
    "NetIncomeLoss",
    "EarningsPerShareBasic",
    "CommonStockSharesOutstanding",
    "StockholdersEquity",
    "LongTermDebt",
    "OperatingCashFlow",
    "ResearchAndDevelopmentExpense",
]


def _get_latest_metric(metrics: list[dict], name: str) -> dict | None:
    """Return the most recent annual metric matching `name`."""
    candidates = [
        m for m in metrics
        if m["name"] == name and m.get("period_type") == "annual"
    ]
    if not candidates:
        # Try any period_type
        candidates = [m for m in metrics if m["name"] == name]
    if not candidates:
        return None
    return max(candidates, key=lambda m: m.get("period", ""))


def compare(
    symbols: list[str],
    output_root: Path,
    depth: str = "quick",
    as_of: date | None = None,
    dry_run: bool = False,
) -> dict:
    """
    Build a comparison dict for `symbols`.  For each symbol:
    - Looks for an existing run in the DB.
    - If no run exists, triggers a quick analysis.
    Returns a dict ready for export_compare().
    """
    from company_research.storage.database import Database

    if as_of is None:
        as_of = date.today()

    db_path = output_root / "research.db"
    db = Database(db_path)

    rows: dict[str, dict] = {}

    for sym in symbols:
        sym = sym.upper()
        run = db.get_latest_run(sym)
        if run is None:
            log.info("No run found for %s — running quick analysis for comparison.", sym)
            from company_research.pipeline import analyze
            new_run = analyze(
                symbol=sym,
                depth=depth,
                as_of=as_of,
                lookback_years=3,
                output_root=output_root,
                dry_run=dry_run,
            )
            run = db.get_run_by_id(new_run.run_id)

        if run is None:
            log.warning("Could not obtain a run for %s — skipping.", sym)
            continue

        metrics = db.get_metrics(run["run_id"])
        peers = db.get_peers(run["run_id"])
        conclusions = db.get_conclusions(run["run_id"])

        metric_snapshot: dict[str, dict | None] = {
            name: _get_latest_metric(metrics, name) for name in _COMPARE_METRICS
        }

        rows[sym] = {
            "run_id": run["run_id"],
            "as_of_date": run["as_of_date"],
            "depth": run["depth"],
            "peers": [p["peer_symbol"] for p in peers],
            "metrics": metric_snapshot,
            "conclusions_count": len(conclusions),
        }

    return {
        "symbols": list(rows.keys()),
        "as_of_date": as_of.isoformat(),
        "companies": rows,
    }
