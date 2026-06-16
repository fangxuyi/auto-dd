"""Run flow recorder — tracks each pipeline step's status and key metrics."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any


_STATUS_SYMBOL = {
    "completed": "✓",
    "skipped":   "–",
    "failed":    "✗",
    "partial":   "~",
}


class StepRecord:
    __slots__ = (
        "step_id", "name", "status", "skip_reason",
        "metrics", "warnings", "started_at", "duration_s", "_t0",
    )

    def __init__(self, step_id: str, name: str) -> None:
        self.step_id = step_id
        self.name = name
        self.status = "completed"
        self.skip_reason: str | None = None
        self.metrics: dict[str, Any] = {}
        self.warnings: list[str] = []
        self.started_at: str = datetime.utcnow().isoformat()
        self.duration_s: float = 0.0
        self._t0 = time.monotonic()

    def finish(
        self,
        status: str = "completed",
        skip_reason: str | None = None,
        **metrics: Any,
    ) -> None:
        self.status = status
        self.skip_reason = skip_reason
        self.metrics.update(metrics)
        self.duration_s = round(time.monotonic() - self._t0, 2)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "step":       self.step_id,
            "name":       self.name,
            "status":     _STATUS_SYMBOL.get(self.status, self.status) + " " + self.status,
            "started_at": self.started_at,
            "duration_s": self.duration_s,
        }
        if self.skip_reason:
            d["skip_reason"] = self.skip_reason
        if self.metrics:
            d["metrics"] = self.metrics
        if self.warnings:
            d["warnings"] = self.warnings
        return d


class RunFlowRecorder:
    """Collects StepRecords across a pipeline run and serialises to a flow dict."""

    def __init__(
        self,
        run_id: str,
        symbol: str,
        depth: str,
        as_of_date: str,
        dry_run: bool,
        model_id: str,
    ) -> None:
        self.run_id = run_id
        self.symbol = symbol
        self.depth = depth
        self.as_of_date = as_of_date
        self.dry_run = dry_run
        self.model_id = model_id
        self.started_at = datetime.utcnow().isoformat()
        self.completed_at: str | None = None
        self.run_status: str = "running"
        self._steps: list[StepRecord] = []

    # ── step lifecycle ───────────────────────────────────────────────────────

    def begin(self, step_id: str, name: str) -> StepRecord:
        rec = StepRecord(step_id, name)
        self._steps.append(rec)
        return rec

    def skip(self, step_id: str, name: str, reason: str) -> StepRecord:
        rec = self.begin(step_id, name)
        rec.finish(status="skipped", skip_reason=reason)
        return rec

    def finish_run(self, status: str) -> None:
        self.run_status = status
        self.completed_at = datetime.utcnow().isoformat()

    # ── serialisation ────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id":       self.run_id,
            "symbol":       self.symbol,
            "depth":        self.depth,
            "as_of_date":   self.as_of_date,
            "dry_run":      self.dry_run,
            "model_id":     self.model_id,
            "run_status":   _STATUS_SYMBOL.get(self.run_status, self.run_status)
                            + " " + self.run_status,
            "started_at":   self.started_at,
            "completed_at": self.completed_at,
            "steps":        [s.to_dict() for s in self._steps],
        }
