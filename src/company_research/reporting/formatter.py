from __future__ import annotations

import re
from pathlib import Path


def write_report(
    report_md: str,
    sources: list[dict],
    out_dir: Path,
) -> None:
    """Write report.md and executive_summary.md to out_dir.

    Citation tags `[src:SOURCE_ID]` are replaced with short readable references
    using the sources list from the DB.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    source_map = {s["source_id"]: s for s in sources}
    resolved = _resolve_citations(report_md, source_map)

    (out_dir / "report.md").write_text(resolved, encoding="utf-8")

    summary = _extract_executive_summary(resolved)
    (out_dir / "executive_summary.md").write_text(summary, encoding="utf-8")


def _resolve_citations(text: str, source_map: dict[str, dict]) -> str:
    """Replace [src:SOURCE_ID] tags with readable short references."""

    def _replace(m: re.Match) -> str:  # type: ignore[type-arg]
        src_id = m.group(1)
        src = source_map.get(src_id)
        if not src:
            return f"[{src_id}]"
        title = src.get("title", src_id)
        date = src.get("published_date") or src.get("accessed_date", "")[:10]
        short = title[:60] + ("…" if len(title) > 60 else "")
        return f"[{short}, {date}]" if date else f"[{short}]"

    return re.sub(r"\[src:([^\]]+)\]", _replace, text)


def _extract_executive_summary(report_md: str) -> str:
    """Extract the Executive Summary section (section 1) from the full report."""
    # Match ## 1. Executive Summary through the next ## section
    m = re.search(
        r"(##\s+1\.\s+Executive Summary.*?)(?=\n##\s+\d+\.|\Z)",
        report_md,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        # Fallback: return first 2000 chars
        return report_md[:2000] + ("\n\n*[Truncated — full report in report.md]*" if len(report_md) > 2000 else "")

    # Include the report header (everything before the first ##)
    header_m = re.match(r"(^#[^#].*?)(?=\n##)", report_md, re.DOTALL)
    header = header_m.group(1).strip() + "\n\n" if header_m else ""
    return header + m.group(1).strip()
