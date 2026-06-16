from __future__ import annotations

import re
from pathlib import Path


def write_report(
    report_md: str,
    sources: list[dict],
    out_dir: Path,
    contradictions: list[dict] | None = None,
    conclusions: list[dict] | None = None,
) -> None:
    """Write report.md and executive_summary.md to out_dir.

    Citation tags ``[src:SOURCE_ID]`` are replaced with short readable references
    using the sources list from the DB.  Bare ``[UUID]`` citations emitted by the
    synthesis LLM are resolved against either the source map or, when the UUID
    belongs to a section conclusion, against the conclusions list.
    If contradictions are provided, a flagged-contradictions section is appended.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    source_map = {s["source_id"]: s for s in sources}
    conclusion_map = {c["conclusion_id"]: c for c in (conclusions or [])}
    resolved = _resolve_citations(report_md, source_map, conclusion_map)

    if contradictions:
        resolved = resolved.rstrip() + "\n\n" + _format_contradictions_md(contradictions)

    (out_dir / "report.md").write_text(resolved, encoding="utf-8")

    summary = _extract_executive_summary(resolved)
    (out_dir / "executive_summary.md").write_text(summary, encoding="utf-8")


def _format_contradictions_md(contradictions: list[dict]) -> str:
    """Append a contradictions section to the markdown report."""
    material = [c for c in contradictions if c.get("severity", "").lower() == "material"]
    minor    = [c for c in contradictions if c.get("severity", "").lower() != "material"]

    lines = [
        "---",
        "",
        "## Contradictions Flagged",
        "",
        "> The following pairs of facts from different source documents are in direct conflict.",
        "> **Material contradictions must be reviewed before relying on conclusions in this report.**",
        "",
    ]

    def _entry(c: dict, badge: str) -> list[str]:
        desc = c.get("description", "").strip()
        res  = c.get("resolution", "").strip()
        out  = [f"### {badge} {desc[:80]}{'…' if len(desc) > 80 else ''}", ""]
        if len(desc) > 80:
            out += [desc, ""]
        if res:
            out += [f"**Resolution:** {res}", ""]
        return out

    if material:
        lines += ["#### Material", ""]
        for c in material:
            lines += _entry(c, "⚠")
    if minor:
        lines += ["#### Minor", ""]
        for c in minor:
            lines += _entry(c, "ℹ")

    return "\n".join(lines) + "\n"


_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)


def _resolve_citations(
    text: str,
    source_map: dict[str, dict],
    conclusion_map: dict[str, dict] | None = None,
) -> str:
    """Replace citation tags with readable short references.

    Handles:
    - ``[src:SOURCE_ID]`` — canonical format pointing to a source record
    - bare ``[UUID]`` — emitted by the synthesis LLM; resolved against
      source_map first, then conclusion_map (section analysis back-references)
    """
    conclusion_map = conclusion_map or {}

    def _format_source(src_id: str) -> str:
        src = source_map.get(src_id)
        if not src:
            return f"[{src_id}]"
        title = src.get("title", src_id)
        date = src.get("published_date") or src.get("accessed_date", "")[:10]
        short = title[:60] + ("…" if len(title) > 60 else "")
        return f"[{short}, {date}]" if date else f"[{short}]"

    def _format_conclusion(_: dict) -> str:
        return ""  # strip bare conclusion-id citations — they're internal references

    # Pass 1: canonical [src:SOURCE_ID]
    text = re.sub(r"\[src:([^\]]+)\]", lambda m: _format_source(m.group(1)), text)

    # Pass 2: bare [UUID] — resolve against sources then conclusions
    def _bare(m: re.Match) -> str:  # type: ignore[type-arg]
        uid = m.group(1)
        if uid in source_map:
            return _format_source(uid)
        if uid in conclusion_map:
            return _format_conclusion(conclusion_map[uid])
        return m.group(0)  # leave truly unknown UUIDs untouched

    return re.sub(r"\[(" + _UUID_RE.pattern + r")\]", _bare, text)


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
