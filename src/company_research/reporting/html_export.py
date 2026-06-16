"""Convert auto-dd report.md files to self-contained styled HTML.

If value_chain_graph.json and/or sources.json are present in the same
directory as report.md they are automatically embedded.

The generated HTML includes:
  • Report      — the existing styled research report
  • Value Chain — D3 force-directed supply-chain graph + relationship table
  • Sources     — all indexed source documents with links
  • Ask         — interactive RAG Q&A panel (calls localhost:PORT/ask)
"""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# ── constants ─────────────────────────────────────────────────────────────────

_QA_PORT_DEFAULT = 7234

_UUID_RE = re.compile(
    r"\[([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\]"
)
_BOLD_RE   = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_META_LINE_RE     = re.compile(r"^\*\*(.+?):\*\*\s*(.+)$")
_SECTION_HEADING_RE = re.compile(r"^##\s+(\d+)\.\s+(.+)$")

_CONC_KEYS: dict[str, str] = {
    "**Conclusion:**":                    "conclusion",
    "**Confidence:**":                    "confidence",
    "**Counterevidence:**":              "counterevidence",
    "**What would change this conclusion:**": "what_would_change",
}
_CONF_CLASS: dict[str, str] = {"low": "low", "medium": "medium", "high": "high"}


# ── data model ────────────────────────────────────────────────────────────────

@dataclass
class SectionData:
    number: int
    title: str
    body_paragraphs: list[str] = field(default_factory=list)
    conclusion: str = ""
    confidence: str = ""
    counterevidence: str = ""
    what_would_change: str = ""


@dataclass
class ReportData:
    company: str = ""
    ticker:  str = ""
    subtitle: str = ""
    metadata: dict[str, str] = field(default_factory=dict)
    sections: list[SectionData] = field(default_factory=list)
    footer: str = ""


# ── inline markdown ───────────────────────────────────────────────────────────

def _inline_md(text: str) -> str:
    out = html.escape(text)
    out = _UUID_RE.sub(
        lambda m: (
            f'<cite class="cit" title="{m.group(1)}">'
            f"<span>{m.group(1)[:8]}</span></cite>"
        ),
        out,
    )
    out = _BOLD_RE.sub(r"<strong>\1</strong>", out)
    out = _ITALIC_RE.sub(r"<em>\1</em>", out)
    return out


# ── parsing ───────────────────────────────────────────────────────────────────

def _parse_header(text: str) -> tuple[str, str, str, dict[str, str]]:
    company = ticker = subtitle = ""
    metadata: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# "):
            rest = line[2:].strip()
            tk = re.search(r"\(([A-Z]{1,5})\)", rest)
            if tk:
                ticker = tk.group(1)
            if " — " in rest:
                left, subtitle = rest.split(" — ", 1)
            else:
                left = rest
            company = re.sub(r"\s*\([A-Z]{1,5}\)", "", left).strip()
        else:
            m = _META_LINE_RE.match(line)
            if m:
                metadata[m.group(1)] = m.group(2)
    return company, ticker, subtitle, metadata


def _paragraphs_from_lines(lines: list[str]) -> list[str]:
    paras: list[str] = []
    buf: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped:
            buf.append(stripped)
        elif buf:
            paras.append(" ".join(buf))
            buf = []
    if buf:
        paras.append(" ".join(buf))
    return paras


def _parse_section_body(text: str) -> SectionData | None:
    lines = text.strip().splitlines()
    for i, raw in enumerate(lines):
        m = _SECTION_HEADING_RE.match(raw.strip())
        if m:
            sec = SectionData(number=int(m.group(1)), title=m.group(2))
            rest = lines[i + 1:]
            # Split body from embedded conclusion block
            conc_idx = next(
                (j for j, l in enumerate(rest) if l.strip().startswith("**Conclusion:**")),
                None,
            )
            if conc_idx is not None:
                sec.body_paragraphs = _paragraphs_from_lines(rest[:conc_idx])
                _parse_conclusion("\n".join(rest[conc_idx:]), sec)
            else:
                sec.body_paragraphs = _paragraphs_from_lines(rest)
            return sec
    return None


def _parse_conclusion(text: str, sec: SectionData) -> None:
    current: str | None = None
    buf: list[str] = []

    def flush() -> None:
        if current is None or not buf:
            return
        value = " ".join(" ".join(l.split()) for l in buf if l.strip())
        if current == "conclusion":        sec.conclusion      = value
        elif current == "confidence":      sec.confidence      = value
        elif current == "counterevidence": sec.counterevidence = value
        elif current == "what_would_change": sec.what_would_change = value

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        matched = False
        for marker, key in _CONC_KEYS.items():
            if line.startswith(marker):
                flush(); buf = []; current = key
                rest = line[len(marker):].strip()
                if rest:
                    buf.append(rest)
                matched = True
                break
        if not matched and current is not None:
            buf.append(line)
    flush()


def parse_report(md_text: str) -> ReportData:
    chunks = re.split(r"\n---\n", md_text)
    data = ReportData()
    if not chunks:
        return data
    data.company, data.ticker, data.subtitle, data.metadata = _parse_header(chunks[0])
    for chunk in chunks[1:]:
        chunk = chunk.strip()
        sec = _parse_section_body(chunk)
        if sec is not None:
            data.sections.append(sec)
        elif chunk.startswith("*") and not chunk.startswith("**"):
            data.footer = chunk.strip("*").strip()
    return data


# ── CSS ───────────────────────────────────────────────────────────────────────

_CSS = """\
@import url('https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,500;0,600;1,400&family=Lora:ital,wght@0,400;0,500;1,400&family=IBM+Plex+Mono:wght@400;500&display=swap');

*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}

:root {
  --bg:        #060A1A;
  --surface:   #0C1128;
  --surface-hi:#121B35;
  --border:    #1C2842;
  --border-sub:#131C32;
  --text:      #DDD3BC;
  --text-2:    #7A8BAA;
  --text-3:    #485570;
  --gold:      #C4962A;
  --gold-l:    #D4AC54;
  --gold-d:    rgba(196,150,42,.12);
  --gold-glow: rgba(196,150,42,.25);
  --blue:      #4A84C4;
  --blue-l:    #6BA0D8;
  --blue-d:    rgba(74,132,196,.11);
  --green:     #3A9E72;
  --green-l:   #52B88A;
  --green-d:   rgba(58,158,114,.11);
  --amber:     #D4900A;
  --amber-l:   #E6A82A;
  --amber-d:   rgba(212,144,10,.12);
  --font-d:"EB Garamond",Georgia,serif;
  --font-b:"Lora",Georgia,serif;
  --font-m:"IBM Plex Mono","Courier New",monospace;
}

html{scroll-behavior:smooth}

body {
  background:var(--bg);
  color:var(--text);
  font-family:var(--font-b);
  font-size:17px;
  line-height:1.78;
  -webkit-font-smoothing:antialiased;
}

body::before {
  content:"";
  position:fixed;inset:0;
  background-image:
    linear-gradient(rgba(196,150,42,.018) 1px,transparent 1px),
    linear-gradient(90deg,rgba(196,150,42,.018) 1px,transparent 1px);
  background-size:64px 64px;
  pointer-events:none;z-index:0;
}

body::after {
  content:"";
  position:fixed;top:0;left:0;right:0;height:2px;
  background:linear-gradient(90deg,var(--gold),rgba(196,150,42,0));
  z-index:1000;
}

/* ── tab nav ── */
.tab-nav {
  position:sticky;
  top:0;
  z-index:500;
  display:flex;
  gap:0;
  background:rgba(6,10,26,.92);
  backdrop-filter:blur(12px);
  border-bottom:1px solid var(--border);
  padding:0 2.5rem;
}

.tab-btn {
  font-family:var(--font-m);
  font-size:0.6rem;
  text-transform:uppercase;
  letter-spacing:0.2em;
  color:var(--text-3);
  background:none;
  border:none;
  border-bottom:2px solid transparent;
  padding:0.95rem 1.1rem;
  cursor:pointer;
  transition:color .15s, border-color .15s;
  white-space:nowrap;
}

.tab-btn:hover { color:var(--text-2) }
.tab-btn.active {
  color:var(--gold-l);
  border-bottom-color:var(--gold);
}

/* ── panels ── */
.tab-panel { display:none }
.tab-panel.active { display:block }

/* ── report panel ── */
.report-wrap {
  max-width:800px;
  margin:0 auto;
  padding:0 2.5rem 7rem;
  position:relative;z-index:1;
}

.hero {
  padding:5.5rem 0 3rem;
  border-bottom:1px solid var(--border);
}
.hero-eyebrow {
  display:flex;align-items:center;gap:0.9rem;margin-bottom:1.75rem;
}
.hero-ticker {
  font-family:var(--font-m);font-size:0.68rem;font-weight:500;
  letter-spacing:0.22em;text-transform:uppercase;color:var(--gold-l);
  background:var(--gold-d);border:1px solid rgba(196,150,42,.28);
  padding:0.22rem 0.7rem;border-radius:3px;
}
.hero-exchange {
  font-family:var(--font-m);font-size:0.62rem;color:var(--text-3);
  letter-spacing:0.1em;text-transform:uppercase;
}
.hero-company {
  font-family:var(--font-d);font-size:clamp(2.5rem,5.5vw,4rem);
  font-weight:500;letter-spacing:-0.01em;line-height:1.08;
  color:var(--text);margin-bottom:0.6rem;
}
.hero-subtitle {
  font-family:var(--font-d);font-size:1.15rem;color:var(--text-2);
  font-style:italic;margin-bottom:2.5rem;
}
.meta-strip {
  display:flex;flex-wrap:wrap;gap:0.2rem 2.5rem;
  padding:1.25rem 0;
  border-top:1px solid var(--border-sub);
  border-bottom:1px solid var(--border-sub);
}
.meta-item { display:flex;flex-direction:column;gap:0.12rem }
.meta-key {
  font-family:var(--font-m);font-size:0.53rem;text-transform:uppercase;
  letter-spacing:0.14em;color:var(--text-3);
}
.meta-val { font-family:var(--font-m);font-size:0.72rem;color:var(--gold-l) }
.toc {
  padding:2.5rem 0;border-bottom:1px solid var(--border);
}
.toc-label {
  font-family:var(--font-m);font-size:0.55rem;text-transform:uppercase;
  letter-spacing:0.18em;color:var(--text-3);margin-bottom:1rem;
}
.toc-list { list-style:none }
.toc-list li { border-bottom:1px solid var(--border-sub) }
.toc-list a {
  display:flex;align-items:baseline;gap:0.85rem;text-decoration:none;
  color:var(--text-2);font-family:var(--font-d);font-size:1rem;
  padding:0.55rem 0;transition:color .15s,padding-left .15s;
}
.toc-list a:hover { color:var(--gold-l);padding-left:0.4rem }
.toc-num {
  font-family:var(--font-m);font-size:0.6rem;color:var(--gold);
  min-width:1.6rem;letter-spacing:0.05em;
}
.sections { padding-top:0.5rem }
.report-section {
  position:relative;padding:4.5rem 0 2.5rem;
  border-bottom:1px solid var(--border-sub);
  opacity:0;animation:rise .55s cubic-bezier(.22,.68,0,1.1) forwards;
}
@keyframes rise {
  from{opacity:0;transform:translateY(16px)}
  to  {opacity:1;transform:translateY(0)}
}
.section-numeral {
  position:absolute;top:2rem;left:-2rem;font-family:var(--font-d);
  font-size:9rem;font-weight:600;color:rgba(196,150,42,.045);
  line-height:1;pointer-events:none;user-select:none;z-index:0;
}
.section-head { position:relative;z-index:1;margin-bottom:1.85rem }
.section-index {
  font-family:var(--font-m);font-size:0.57rem;text-transform:uppercase;
  letter-spacing:0.18em;color:var(--gold);margin-bottom:0.35rem;
}
.section-title {
  font-family:var(--font-d);font-size:1.85rem;font-weight:500;
  color:var(--text);line-height:1.15;
}
.section-body { position:relative;z-index:1 }
.section-body p { margin-bottom:1.1rem;color:var(--text);font-size:1rem }
.section-body p:last-child { margin-bottom:0 }
cite.cit {
  font-style:normal;font-family:var(--font-m);font-size:0.56em;
  vertical-align:super;line-height:0;color:var(--gold);
  background:var(--gold-d);border:1px solid rgba(196,150,42,.22);
  padding:0 3px;border-radius:2px;cursor:help;position:relative;
  white-space:nowrap;transition:background .15s;margin-left:1px;
}
cite.cit:hover { background:var(--gold-glow) }
cite.cit::after {
  content:attr(title);position:absolute;bottom:calc(100% + 5px);
  left:50%;transform:translateX(-50%);background:var(--surface-hi);
  border:1px solid var(--border);color:var(--text-2);font-size:.78rem;
  padding:3px 7px;border-radius:3px;white-space:nowrap;
  opacity:0;pointer-events:none;transition:opacity .15s .08s;z-index:200;
}
cite.cit:hover::after { opacity:1 }
.section-analysis { margin-top:2.75rem;position:relative;z-index:1 }
.conclusion-block {
  padding:1.5rem 1.5rem 1.5rem 1.85rem;border-left:3px solid var(--gold);
  background:var(--gold-d);border-radius:0 6px 6px 0;margin-bottom:0.7rem;
}
.conclusion-header {
  display:flex;align-items:center;gap:0.75rem;margin-bottom:0.8rem;flex-wrap:wrap;
}
.block-eyebrow {
  font-family:var(--font-m);font-size:0.57rem;text-transform:uppercase;
  letter-spacing:0.16em;color:var(--gold-l);
}
.conf-badge {
  display:inline-flex;align-items:center;padding:.15rem .55rem;border-radius:2px;
  font-family:var(--font-m);font-size:.58rem;font-weight:500;
  letter-spacing:.06em;text-transform:uppercase;
}
.conf-badge.low    {background:var(--amber-d);color:var(--amber-l);border:1px solid rgba(212,144,10,.3)}
.conf-badge.medium {background:var(--blue-d); color:var(--blue-l); border:1px solid rgba(74,132,196,.3)}
.conf-badge.high   {background:var(--green-d);color:var(--green-l);border:1px solid rgba(58,158,114,.3)}
.conclusion-block p { font-size:.97rem;color:var(--text);line-height:1.72 }
.detail-block {
  padding:1.1rem 1.25rem 1.1rem 1.6rem;border-left:2px solid;
  border-radius:0 4px 4px 0;margin-bottom:.6rem;
}
.detail-block.cevid  { border-color:var(--blue);background:var(--blue-d) }
.detail-block.change { border-color:var(--green);background:var(--green-d) }
.detail-eyebrow {
  font-family:var(--font-m);font-size:.53rem;text-transform:uppercase;
  letter-spacing:.16em;margin-bottom:.5rem;
}
.cevid  .detail-eyebrow { color:var(--blue-l) }
.change .detail-eyebrow { color:var(--green-l) }
.detail-block p { font-size:.9rem;color:var(--text-2);line-height:1.68 }
.report-footer { padding:3rem 0 0;text-align:center }
.report-footer p {
  font-family:var(--font-d);font-style:italic;font-size:.88rem;color:var(--text-3);
}

/* ── value chain panel ── */
.vc-wrap {
  max-width:1120px;margin:0 auto;padding:3rem 2.5rem 6rem;
}
.vc-section-head {
  margin-bottom:2.5rem;border-bottom:1px solid var(--border);padding-bottom:1.5rem;
}
.vc-section-head h2 {
  font-family:var(--font-d);font-size:2rem;font-weight:500;color:var(--text);
  margin-bottom:.35rem;
}
.vc-section-head p {
  font-family:var(--font-m);font-size:.6rem;letter-spacing:.12em;
  text-transform:uppercase;color:var(--text-3);
}
.vc-stats {
  display:flex;gap:2.5rem;margin-bottom:2.5rem;flex-wrap:wrap;
}
.vc-stat {
  display:flex;flex-direction:column;gap:.2rem;
}
.vc-stat-val {
  font-family:var(--font-d);font-size:2.2rem;font-weight:500;color:var(--gold-l);
  line-height:1;
}
.vc-stat-key {
  font-family:var(--font-m);font-size:.52rem;text-transform:uppercase;
  letter-spacing:.14em;color:var(--text-3);
}
.vc-graph-container {
  position:relative;
  background:var(--surface);
  border:1px solid var(--border);
  border-radius:8px;
  overflow:hidden;
  height:540px;
  margin-bottom:2.5rem;
}
.vc-graph-container svg { width:100%;height:100% }
.vc-tooltip {
  position:absolute;pointer-events:none;
  background:var(--surface-hi);border:1px solid var(--border);
  color:var(--text);font-family:var(--font-m);font-size:.7rem;
  padding:.4rem .7rem;border-radius:4px;
  opacity:0;transition:opacity .12s;
  max-width:220px;line-height:1.4;
  white-space:nowrap;z-index:100;
}
.vc-graph-legend {
  position:absolute;bottom:1rem;left:1rem;
  display:flex;gap:1rem;align-items:center;
}
.legend-item {
  display:flex;align-items:center;gap:.4rem;
  font-family:var(--font-m);font-size:.55rem;
  letter-spacing:.1em;text-transform:uppercase;color:var(--text-3);
}
.legend-dot {
  width:10px;height:10px;border-radius:50%;flex-shrink:0;
}
.vc-table-section { margin-top:1rem }
.vc-table-label {
  font-family:var(--font-m);font-size:.55rem;text-transform:uppercase;
  letter-spacing:.16em;color:var(--text-3);margin-bottom:.85rem;
}
.vc-table {
  width:100%;border-collapse:collapse;font-size:.85rem;
}
.vc-table thead th {
  font-family:var(--font-m);font-size:.52rem;text-transform:uppercase;
  letter-spacing:.12em;color:var(--text-3);
  border-bottom:1px solid var(--border);padding:.5rem .75rem;
  text-align:left;
}
.vc-table tbody tr {
  border-bottom:1px solid var(--border-sub);
  transition:background .1s;
}
.vc-table tbody tr:hover { background:var(--surface-hi) }
.vc-table td {
  padding:.55rem .75rem;color:var(--text-2);
  font-family:var(--font-b);
}
.vc-table td.ticker {
  font-family:var(--font-m);font-size:.72rem;color:var(--gold-l);
}
.vc-badge {
  display:inline-block;
  font-family:var(--font-m);font-size:.5rem;
  text-transform:uppercase;letter-spacing:.1em;
  padding:.12rem .4rem;border-radius:2px;
}
.vc-badge.medium { background:var(--blue-d);color:var(--blue-l);border:1px solid rgba(74,132,196,.25) }
.vc-badge.high   { background:var(--green-d);color:var(--green-l);border:1px solid rgba(58,158,114,.25) }
.vc-badge.low    { background:var(--amber-d);color:var(--amber-l);border:1px solid rgba(212,144,10,.25) }

/* ── sources panel ── */
.sources-wrap {
  max-width:1000px;margin:0 auto;padding:3rem 2.5rem 6rem;
}
.sources-section-head {
  margin-bottom:2.5rem;border-bottom:1px solid var(--border);padding-bottom:1.5rem;
  display:flex;align-items:baseline;gap:1.5rem;
}
.sources-section-head h2 {
  font-family:var(--font-d);font-size:2rem;font-weight:500;color:var(--text);
}
.sources-count {
  font-family:var(--font-m);font-size:.58rem;letter-spacing:.12em;
  text-transform:uppercase;color:var(--text-3);
}
.sources-filter-row {
  display:flex;gap:.5rem;margin-bottom:1.5rem;flex-wrap:wrap;
}
.filter-btn {
  font-family:var(--font-m);font-size:.55rem;text-transform:uppercase;
  letter-spacing:.1em;padding:.3rem .75rem;border-radius:2px;
  border:1px solid var(--border);background:none;color:var(--text-3);
  cursor:pointer;transition:all .15s;
}
.filter-btn:hover { border-color:var(--gold);color:var(--gold-l) }
.filter-btn.active { background:var(--gold-d);border-color:var(--gold);color:var(--gold-l) }
.src-table {
  width:100%;border-collapse:collapse;
}
.src-table thead th {
  font-family:var(--font-m);font-size:.52rem;text-transform:uppercase;
  letter-spacing:.12em;color:var(--text-3);
  border-bottom:1px solid var(--border);padding:.5rem .75rem;text-align:left;
}
.src-table tbody tr {
  border-bottom:1px solid var(--border-sub);transition:background .1s;
}
.src-table tbody tr:hover { background:var(--surface-hi) }
.src-table tbody tr.hidden { display:none }
.src-table td { padding:.65rem .75rem }
.src-type {
  font-family:var(--font-m);font-size:.6rem;color:var(--gold-l);white-space:nowrap;
}
.src-title {
  font-family:var(--font-b);font-size:.88rem;color:var(--text);
}
.src-title a {
  color:inherit;text-decoration:none;
  border-bottom:1px solid var(--border-sub);
  transition:color .15s,border-color .15s;
}
.src-title a:hover { color:var(--gold-l);border-color:var(--gold) }
.src-publisher {
  font-family:var(--font-m);font-size:.6rem;color:var(--text-3);
  white-space:nowrap;
}
.src-date {
  font-family:var(--font-m);font-size:.6rem;color:var(--text-3);
  white-space:nowrap;
}
.tier-dot {
  display:inline-block;width:8px;height:8px;border-radius:50%;
  flex-shrink:0;
}
.tier-1 { background:var(--green-l) }
.tier-2 { background:var(--blue-l) }
.tier-3 { background:var(--gold-l) }
.tier-4,.tier-5,.tier-6 { background:var(--text-3) }
.tier-cell {
  display:flex;align-items:center;gap:.45rem;
  font-family:var(--font-m);font-size:.58rem;color:var(--text-3);
  white-space:nowrap;
}

/* ── ask panel ── */
.ask-wrap {
  max-width:800px;margin:0 auto;padding:3rem 2.5rem 6rem;
}
.ask-section-head {
  margin-bottom:2.5rem;border-bottom:1px solid var(--border);padding-bottom:1.5rem;
  display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:1rem;
}
.ask-section-head h2 {
  font-family:var(--font-d);font-size:2rem;font-weight:500;color:var(--text);
}
.server-badge {
  display:flex;align-items:center;gap:.5rem;
  font-family:var(--font-m);font-size:.58rem;letter-spacing:.1em;
  text-transform:uppercase;color:var(--text-3);
}
.server-dot {
  width:7px;height:7px;border-radius:50%;background:var(--text-3);
  transition:background .3s;flex-shrink:0;
}
.server-dot.online  { background:var(--green-l);box-shadow:0 0 6px var(--green-l) }
.server-dot.offline { background:var(--amber-l) }
.ask-form {
  display:flex;flex-direction:column;gap:.85rem;margin-bottom:2rem;
}
.ask-input {
  width:100%;background:var(--surface);border:1px solid var(--border);
  color:var(--text);font-family:var(--font-m);font-size:.82rem;
  line-height:1.6;padding:.9rem 1rem;border-radius:5px;
  resize:vertical;min-height:72px;
  transition:border-color .15s,box-shadow .15s;
  outline:none;
}
.ask-input:focus {
  border-color:rgba(196,150,42,.5);
  box-shadow:0 0 0 3px rgba(196,150,42,.07);
}
.ask-input::placeholder { color:var(--text-3) }
.ask-row {
  display:flex;align-items:center;justify-content:space-between;gap:1rem;
}
.server-hint {
  font-family:var(--font-m);font-size:.58rem;color:var(--text-3);
  letter-spacing:.08em;
}
.ask-submit {
  font-family:var(--font-m);font-size:.6rem;letter-spacing:.18em;
  text-transform:uppercase;color:var(--bg);
  background:var(--gold);border:none;
  padding:.6rem 1.4rem;border-radius:3px;cursor:pointer;
  transition:background .15s,transform .1s;
  flex-shrink:0;
}
.ask-submit:hover  { background:var(--gold-l) }
.ask-submit:active { transform:scale(.97) }
.ask-submit:disabled {
  background:var(--surface-hi);color:var(--text-3);cursor:not-allowed;
}
.answer-area { display:none }
.answer-area.visible { display:block }
.answer-block {
  background:var(--surface);border:1px solid var(--border);
  border-left:3px solid var(--gold);border-radius:0 6px 6px 0;
  padding:1.5rem 1.5rem 1.5rem 1.75rem;margin-bottom:1rem;
}
.answer-label {
  font-family:var(--font-m);font-size:.53rem;text-transform:uppercase;
  letter-spacing:.16em;color:var(--gold-l);margin-bottom:.75rem;
}
.answer-text {
  font-family:var(--font-b);font-size:.97rem;line-height:1.72;color:var(--text);
  white-space:pre-wrap;
}
.sources-toggle {
  font-family:var(--font-m);font-size:.57rem;text-transform:uppercase;
  letter-spacing:.12em;color:var(--text-3);background:none;border:none;
  cursor:pointer;padding:.3rem 0;transition:color .15s;
  display:flex;align-items:center;gap:.4rem;margin-bottom:.5rem;
}
.sources-toggle:hover { color:var(--text-2) }
.sources-toggle .arrow { transition:transform .2s }
.sources-toggle.open .arrow { transform:rotate(90deg) }
.sources-list { display:none }
.sources-list.open { display:flex;flex-direction:column;gap:.5rem }
.source-chip {
  background:var(--surface);border:1px solid var(--border-sub);
  border-radius:4px;padding:.65rem .9rem;
}
.source-chip-head {
  display:flex;align-items:baseline;gap:.6rem;margin-bottom:.3rem;flex-wrap:wrap;
}
.source-rank {
  font-family:var(--font-m);font-size:.55rem;color:var(--gold);
  min-width:1.4rem;
}
.source-title {
  font-family:var(--font-m);font-size:.62rem;color:var(--text-2);
  flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
}
.source-score {
  font-family:var(--font-m);font-size:.5rem;color:var(--text-3);
}
.source-snippet {
  font-family:var(--font-b);font-size:.8rem;color:var(--text-3);line-height:1.55;
}
.ask-spinner {
  display:none;align-items:center;gap:.6rem;
  font-family:var(--font-m);font-size:.6rem;color:var(--text-3);
  letter-spacing:.1em;text-transform:uppercase;
  padding:.75rem 0;
}
.ask-spinner.visible { display:flex }
.spinner-ring {
  width:14px;height:14px;border-radius:50%;
  border:2px solid var(--border);border-top-color:var(--gold);
  animation:spin .7s linear infinite;flex-shrink:0;
}
@keyframes spin { to{transform:rotate(360deg)} }
.server-offline-notice {
  background:var(--surface);
  border:1px solid var(--border);
  border-radius:6px;padding:1.25rem 1.5rem;margin-bottom:1.5rem;
  display:block;
}
.server-offline-notice.offline {
  border-color:var(--gold);
}
.server-offline-notice-head {
  font-family:var(--font-m);font-size:.55rem;text-transform:uppercase;
  letter-spacing:.16em;color:var(--text-3);margin-bottom:.5rem;
  transition:color .2s;
}
.server-offline-notice.offline .server-offline-notice-head { color:var(--gold) }
.server-offline-notice p {
  font-family:var(--font-b);font-size:.88rem;color:var(--text-3);
  margin-bottom:.85rem;transition:color .2s;
}
.server-offline-notice.offline p { color:var(--text-2) }
.cmd-block {
  display:flex;align-items:center;gap:.75rem;
  background:var(--surface-hi);border:1px solid var(--border);
  border-radius:4px;padding:.65rem 1rem;
}
.cmd-block code {
  font-family:var(--font-m);font-size:.82rem;color:var(--gold-l);
  flex:1;
}
.copy-btn {
  font-family:var(--font-m);font-size:.52rem;text-transform:uppercase;
  letter-spacing:.1em;color:var(--text-3);background:none;
  border:1px solid var(--border);border-radius:2px;
  padding:.25rem .6rem;cursor:pointer;transition:all .15s;white-space:nowrap;
  flex-shrink:0;
}
.copy-btn:hover { color:var(--gold-l);border-color:var(--gold) }
.copy-btn.copied { color:var(--green-l);border-color:var(--green) }

/* ── print / responsive ── */
@media print {
  body{background:#fff;color:#111;font-size:11pt}
  body::before,body::after{display:none}
  .tab-nav{display:none}
  .tab-panel{display:block !important}
  .report-wrap{max-width:100%;padding:0}
  .hero{padding:1rem 0}
  .report-section{page-break-inside:avoid;animation:none !important;opacity:1 !important}
  .section-numeral{display:none}
  cite.cit::after{display:none}
  .toc,.vc-graph-container,.ask-wrap{display:none}
  .sources-wrap{max-width:100%;padding:0}
}

@media(max-width:600px){
  body{font-size:15px}
  .report-wrap,.ask-wrap{padding:0 1.25rem 4rem}
  .vc-wrap{padding:2rem 1.25rem 4rem}
  .section-numeral{font-size:5.5rem;left:-.5rem}
  .hero{padding:3.5rem 0 2rem}
  .hero-company{font-size:2.2rem}
  .tab-nav{padding:0 1rem}
  .tab-btn{padding:.85rem .7rem}
}
"""


# ── JavaScript ────────────────────────────────────────────────────────────────

def _build_js(symbol: str, has_graph: bool, qa_port: int) -> str:
    return f"""
// ── tab switching ──────────────────────────────────────────────────────────
document.querySelectorAll('.tab-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('panel-' + btn.dataset.tab).classList.add('active');
    if (btn.dataset.tab === 'vc' && !window._graphInited && window.GRAPH_DATA) {{
      initGraph();
      window._graphInited = true;
    }}
  }});
}});

// ── value chain graph ──────────────────────────────────────────────────────
window._graphInited = false;
const SYMBOL = {json.dumps(symbol)};

function initGraph() {{
  if (!window.GRAPH_DATA || typeof d3 === 'undefined') return;
  const container = document.getElementById('vc-graph');
  if (!container) return;

  const allNodes = window.GRAPH_DATA.nodes.map(n => ({{
    ...n,
    isTarget: (n.ticker || '').toUpperCase() === SYMBOL.toUpperCase(),
  }}));
  const nodeById = {{}};
  allNodes.forEach(n => nodeById[n.node_id] = n);

  const links = window.GRAPH_DATA.edges
    .filter(e => nodeById[e.source_node_id] && nodeById[e.target_node_id])
    .map(e => ({{
      source: e.source_node_id,
      target: e.target_node_id,
      type: e.relationship_type,
      confidence: e.confidence,
    }}));

  const rect = container.getBoundingClientRect();
  const W = rect.width || 900;
  const H = 540;

  const svg = d3.select(container).append('svg')
    .attr('viewBox', `0 0 ${{W}} ${{H}}`)
    .attr('preserveAspectRatio', 'xMidYMid meet');

  // Arrow marker
  svg.append('defs').append('marker')
    .attr('id', 'arrowhead').attr('viewBox', '0 -4 8 8')
    .attr('refX', 20).attr('refY', 0)
    .attr('markerWidth', 5).attr('markerHeight', 5)
    .attr('orient', 'auto')
    .append('path').attr('fill', 'rgba(196,150,42,.45)')
    .attr('d', 'M0,-4L8,0L0,4');

  const sim = d3.forceSimulation(allNodes)
    .force('link', d3.forceLink(links).id(d => d.node_id).distance(110).strength(0.4))
    .force('charge', d3.forceManyBody().strength(-220))
    .force('center', d3.forceCenter(W / 2, H / 2).strength(0.06))
    .force('collision', d3.forceCollide().radius(d => d.isTarget ? 46 : 28).strength(0.8));

  // Pin the target company at center
  const target = allNodes.find(n => n.isTarget);
  if (target) {{ target.fx = W / 2; target.fy = H / 2; }}

  const linkSel = svg.append('g')
    .selectAll('line').data(links).join('line')
    .attr('stroke', 'rgba(196,150,42,.2)')
    .attr('stroke-width', 1)
    .attr('marker-end', 'url(#arrowhead)');

  const nodeSel = svg.append('g')
    .selectAll('g').data(allNodes).join('g')
    .attr('cursor', 'default');

  nodeSel.append('circle')
    .attr('r', d => d.isTarget ? 26 : 15)
    .attr('fill', d => d.isTarget ? 'var(--gold)' : 'var(--surface-hi)')
    .attr('stroke', d => d.isTarget ? 'var(--gold-l)' : 'var(--border)')
    .attr('stroke-width', d => d.isTarget ? 2 : 1);

  nodeSel.append('text')
    .text(d => d.ticker || d.entity_name.split(' ')[0].slice(0,6))
    .attr('text-anchor', 'middle').attr('dy', '0.35em')
    .attr('fill', d => d.isTarget ? '#060A1A' : 'var(--text-2)')
    .attr('font-size', d => d.isTarget ? '9px' : '6.5px')
    .attr('font-family', 'var(--font-m)')
    .attr('pointer-events', 'none');

  // Tooltip
  const tip = d3.select(container).append('div').attr('class', 'vc-tooltip');
  nodeSel
    .on('mousemove', (event, d) => {{
      const x = event.offsetX, y = event.offsetY;
      tip.style('opacity', 1)
        .style('left', (x + 14) + 'px')
        .style('top',  (y - 32) + 'px')
        .html(`<strong>${{d.entity_name}}</strong><br/>${{d.ticker || ''}}`);
    }})
    .on('mouseleave', () => tip.style('opacity', 0));

  // Drag
  nodeSel.call(d3.drag()
    .on('start', (e, d) => {{ if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }})
    .on('drag',  (e, d) => {{ d.fx = e.x; d.fy = e.y; }})
    .on('end',   (e, d) => {{
      if (!e.active) sim.alphaTarget(0);
      if (!d.isTarget) {{ d.fx = null; d.fy = null; }}
    }})
  );

  sim.on('tick', () => {{
    linkSel
      .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
    nodeSel.attr('transform', d => `translate(${{d.x}},${{d.y}})`);
  }});
}}

// ── Q&A ────────────────────────────────────────────────────────────────────
const QA_URL = 'http://127.0.0.1:{qa_port}';
const dot   = document.getElementById('server-dot');
const hint  = document.getElementById('server-hint');
const notice= document.getElementById('server-offline-notice');

async function checkServer() {{
  try {{
    const r = await fetch(QA_URL + '/health', {{signal: AbortSignal.timeout(1500)}});
    if (r.ok) {{
      dot.className = 'server-dot online';
      hint.textContent = 'Connected · ' + SYMBOL;
      notice.classList.remove('offline');
      return true;
    }}
  }} catch(_) {{}}
  dot.className = 'server-dot offline';
  hint.textContent = 'Server offline';
  notice.classList.add('offline');
  return false;
}}
checkServer();

document.getElementById('ask-form').addEventListener('submit', async e => {{
  e.preventDefault();
  const question = document.getElementById('ask-input').value.trim();
  if (!question) return;

  const btn = document.getElementById('ask-submit');
  const spinner = document.getElementById('ask-spinner');
  const area = document.getElementById('answer-area');

  btn.disabled = true;
  spinner.classList.add('visible');
  area.classList.remove('visible');

  const online = await checkServer();
  if (!online) {{
    btn.disabled = false;
    spinner.classList.remove('visible');
    return;
  }}

  try {{
    const res = await fetch(QA_URL + '/ask', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{question, k: 12}}),
    }});
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    document.getElementById('answer-text').textContent = data.answer || '';
    const srcList = document.getElementById('sources-list');
    srcList.innerHTML = (data.sources || []).map((s, i) => `
      <div class="source-chip">
        <div class="source-chip-head">
          <span class="source-rank">[${'{'}i+1{'}'}]</span>
          <span class="source-title" title="${{s.title}}">${{s.source_type}} — ${{s.title}}</span>
          <span class="source-score">score ${{s.score}}</span>
        </div>
        <div class="source-snippet">${{s.snippet}}</div>
      </div>`).join('');
    area.classList.add('visible');
  }} catch(err) {{
    document.getElementById('answer-text').textContent = 'Error: ' + err.message;
    area.classList.add('visible');
  }} finally {{
    btn.disabled = false;
    spinner.classList.remove('visible');
  }}
}});

document.getElementById('sources-toggle').addEventListener('click', function() {{
  this.classList.toggle('open');
  document.getElementById('sources-list').classList.toggle('open');
}});

// copy-to-clipboard for server command
const copyBtn = document.getElementById('copy-cmd');
if (copyBtn) {{
  copyBtn.addEventListener('click', () => {{
    navigator.clipboard.writeText(copyBtn.dataset.cmd).then(() => {{
      copyBtn.textContent = 'Copied!';
      copyBtn.classList.add('copied');
      setTimeout(() => {{ copyBtn.textContent = 'Copy'; copyBtn.classList.remove('copied'); }}, 1800);
    }});
  }});
}}

// sources filter
document.querySelectorAll('.filter-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    const type = btn.dataset.type;
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('.src-row').forEach(row => {{
      row.classList.toggle('hidden', type !== 'all' && row.dataset.type !== type);
    }});
  }});
}});
"""


# ── HTML rendering ────────────────────────────────────────────────────────────

def _render_meta(metadata: dict[str, str]) -> str:
    items_html = "\n".join(
        f'    <div class="meta-item">'
        f'<span class="meta-key">{html.escape(k)}</span>'
        f'<span class="meta-val">{html.escape(v)}</span>'
        f"</div>"
        for k, v in metadata.items()
    )
    return f'<div class="meta-strip">\n{items_html}\n  </div>'


def _render_toc(sections: list[SectionData]) -> str:
    items = "\n".join(
        f'    <li><a href="#s{s.number}">'
        f'<span class="toc-num">{s.number:02d}</span>'
        f"{html.escape(s.title)}</a></li>"
        for s in sections
    )
    return (
        f'<nav class="toc" aria-label="Contents">\n'
        f'  <div class="toc-label">Contents</div>\n'
        f'  <ul class="toc-list">\n{items}\n  </ul>\n</nav>'
    )


def _render_section(sec: SectionData, idx: int) -> str:
    delay = f"{0.08 + idx * 0.07:.2f}s"
    num_str = f"{sec.number:02d}"
    body_html = "\n".join(f"    <p>{_inline_md(p)}</p>" for p in sec.body_paragraphs)

    analysis_html = ""
    if sec.conclusion or sec.counterevidence or sec.what_would_change:
        conf_lower = sec.confidence.lower()
        conf_cls = _CONF_CLASS.get(conf_lower, "medium")
        conf_badge = (
            f'<span class="conf-badge {conf_cls}">'
            f"{html.escape(sec.confidence)} confidence</span>"
            if sec.confidence else ""
        )
        conc_p = f"<p>{_inline_md(sec.conclusion)}</p>" if sec.conclusion else ""
        cevid_html = (
            f'\n  <div class="detail-block cevid">'
            f'\n    <div class="detail-eyebrow">Counterevidence</div>'
            f"\n    <p>{_inline_md(sec.counterevidence)}</p>"
            f"\n  </div>"
        ) if sec.counterevidence else ""
        change_html = (
            f'\n  <div class="detail-block change">'
            f'\n    <div class="detail-eyebrow">What would change this conclusion</div>'
            f"\n    <p>{_inline_md(sec.what_would_change)}</p>"
            f"\n  </div>"
        ) if sec.what_would_change else ""
        analysis_html = (
            f'\n<div class="section-analysis">'
            f'\n  <div class="conclusion-block">'
            f'\n    <div class="conclusion-header">'
            f'\n      <span class="block-eyebrow">Conclusion</span>'
            f"\n      {conf_badge}"
            f"\n    </div>"
            f"\n    {conc_p}"
            f"\n  </div>"
            f"{cevid_html}{change_html}"
            f"\n</div>"
        )

    return (
        f'\n<section class="report-section" id="s{sec.number}"'
        f' style="animation-delay:{delay}">'
        f'\n  <div class="section-numeral" aria-hidden="true">{num_str}</div>'
        f'\n  <div class="section-head">'
        f'\n    <div class="section-index">Section {num_str}</div>'
        f'\n    <h2 class="section-title">{html.escape(sec.title)}</h2>'
        f"\n  </div>"
        f'\n  <div class="section-body">\n{body_html}\n  </div>'
        f"{analysis_html}"
        f"\n</section>"
    )


def _render_vc_panel(graph_data: dict | None) -> str:
    if not graph_data:
        return ""

    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])
    symbol = graph_data.get("symbol", "")
    n_nodes = len(nodes)
    n_edges = len(edges)

    # Relationship table — sort: target node last, rest alpha by name
    target_node_id = next(
        (n["node_id"] for n in nodes if (n.get("ticker") or "").upper() == symbol.upper()),
        None,
    )
    suppliers = [n for n in nodes if n.get("node_id") != target_node_id]
    suppliers.sort(key=lambda n: n.get("entity_name", ""))

    # Build edge lookup for confidence
    edge_conf: dict[str, str] = {}
    for e in edges:
        edge_conf[e.get("source_node_id", "")] = e.get("confidence", "medium")

    rows = ""
    for n in suppliers:
        ticker = html.escape(n.get("ticker") or "—")
        name   = html.escape(n.get("entity_name", ""))
        conf   = edge_conf.get(n.get("node_id", ""), "medium")
        conf_e = html.escape(conf)
        rows += (
            f'<tr><td class="ticker">{ticker}</td>'
            f"<td>{name}</td>"
            f'<td><span class="vc-badge {conf_e}">{conf_e}</span></td>'
            f"<td>SUPPLIES</td></tr>\n"
        )

    return f"""
<div class="vc-wrap">
  <div class="vc-section-head">
    <h2>Value Chain</h2>
    <p>{html.escape(symbol)} supply-chain network · sourced from EDGAR filings</p>
  </div>
  <div class="vc-stats">
    <div class="vc-stat">
      <span class="vc-stat-val">{n_nodes}</span>
      <span class="vc-stat-key">Graph nodes</span>
    </div>
    <div class="vc-stat">
      <span class="vc-stat-val">{n_edges}</span>
      <span class="vc-stat-key">Confirmed edges</span>
    </div>
    <div class="vc-stat">
      <span class="vc-stat-val">{len(suppliers)}</span>
      <span class="vc-stat-key">Suppliers identified</span>
    </div>
  </div>

  <div class="vc-graph-container" id="vc-graph">
    <div class="vc-graph-legend">
      <div class="legend-item">
        <div class="legend-dot" style="background:var(--gold)"></div>
        {html.escape(symbol)}
      </div>
      <div class="legend-item">
        <div class="legend-dot" style="background:var(--surface-hi);border:1px solid var(--border)"></div>
        Supplier / partner
      </div>
    </div>
  </div>

  <div class="vc-table-section">
    <div class="vc-table-label">Upstream relationships ({len(suppliers)})</div>
    <table class="vc-table">
      <thead>
        <tr>
          <th>Ticker</th>
          <th>Company</th>
          <th>Confidence</th>
          <th>Relationship</th>
        </tr>
      </thead>
      <tbody>
        {rows}
      </tbody>
    </table>
  </div>
</div>
"""


def _render_sources_panel(sources: list[dict]) -> str:
    if not sources:
        return "<div class='sources-wrap'><p style='padding:3rem;color:var(--text-3);font-family:var(--font-m);font-size:.7rem'>No sources.json found in run directory.</p></div>"

    # Collect unique source types for filter buttons
    types = sorted({s.get("source_type", "unknown") for s in sources})
    filter_btns = '<button class="filter-btn active" data-type="all">All</button>\n'
    filter_btns += "\n".join(
        f'    <button class="filter-btn" data-type="{html.escape(t)}">{html.escape(t)}</button>'
        for t in types
    )

    _tier_label = {1: "Primary (Tier 1)", 2: "Tier 2", 3: "Tier 3", 4: "Tier 4", 5: "Tier 5", 6: "Tier 6"}

    rows = ""
    for s in sources:
        title    = html.escape(s.get("title", "—"))
        url      = html.escape(s.get("url") or "")
        stype    = html.escape(s.get("source_type", "—"))
        pub      = html.escape(s.get("publisher") or "—")
        pdate    = html.escape((s.get("published_date") or "—")[:10])
        tier     = s.get("reliability_tier", 0)
        tier_cls = f"tier-{tier}" if 1 <= tier <= 6 else ""
        tier_lbl = html.escape(_tier_label.get(tier, f"Tier {tier}"))
        title_cell = (
            f'<a href="{url}" target="_blank" rel="noopener">{title}</a>'
            if url else title
        )
        rows += (
            f'<tr class="src-row" data-type="{stype}">'
            f'<td class="src-type">{stype}</td>'
            f'<td class="src-title">{title_cell}</td>'
            f'<td class="src-publisher">{pub}</td>'
            f'<td class="src-date">{pdate}</td>'
            f'<td><div class="tier-cell"><div class="tier-dot {tier_cls}"></div>{tier_lbl}</div></td>'
            f"</tr>\n"
        )

    return f"""
<div class="sources-wrap">
  <div class="sources-section-head">
    <h2>Sources</h2>
    <span class="sources-count">{len(sources)} documents indexed</span>
  </div>
  <div class="sources-filter-row">
    {filter_btns}
  </div>
  <table class="src-table">
    <thead>
      <tr>
        <th>Type</th>
        <th>Title</th>
        <th>Publisher</th>
        <th>Date</th>
        <th>Reliability</th>
      </tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
</div>
"""


def _render_qa_panel(symbol: str, qa_port: int, as_of: str = "<date>") -> str:
    cmd_plain = f"company-research serve research/{symbol}/{as_of}/report.md --port {qa_port}"
    return f"""
<div class="ask-wrap">
  <div class="ask-section-head">
    <h2>Ask</h2>
    <div class="server-badge">
      <div class="server-dot" id="server-dot"></div>
      <span id="server-hint">Checking server…</span>
    </div>
  </div>

  <div class="server-offline-notice" id="server-offline-notice">
    <div class="server-offline-notice-head">Start RAG server</div>
    <p>Run this in a terminal to enable Q&amp;A from the indexed evidence:</p>
    <div class="cmd-block">
      <code id="cmd-text">{html.escape(cmd_plain)}</code>
      <button class="copy-btn" id="copy-cmd" data-cmd="{html.escape(cmd_plain)}">Copy</button>
    </div>
  </div>

  <form class="ask-form" id="ask-form" autocomplete="off">
    <textarea
      id="ask-input"
      class="ask-input"
      placeholder="Ask anything about {html.escape(symbol)} — e.g. &ldquo;What are the main revenue segments?&rdquo; or &ldquo;What supply chain risks are disclosed?&rdquo;"
      rows="3"
    ></textarea>
    <div class="ask-row">
      <span class="server-hint" id="server-status-inline"></span>
      <button type="submit" id="ask-submit" class="ask-submit">Ask →</button>
    </div>
  </form>

  <div class="ask-spinner" id="ask-spinner">
    <div class="spinner-ring"></div>
    Searching evidence…
  </div>

  <div class="answer-area" id="answer-area">
    <div class="answer-block">
      <div class="answer-label">Answer</div>
      <div class="answer-text" id="answer-text"></div>
    </div>
    <button class="sources-toggle" id="sources-toggle">
      <span class="arrow">▶</span> Sources
    </button>
    <div class="sources-list" id="sources-list"></div>
  </div>
</div>
"""


def render_html(
    data: ReportData,
    graph_data: dict | None = None,
    sources_data: list[dict] | None = None,
    qa_port: int = _QA_PORT_DEFAULT,
) -> str:
    exchange  = data.metadata.get("Primary listing", "")
    meta_html = _render_meta(data.metadata)
    toc_html  = _render_toc(data.sections)
    sections_html = "\n".join(_render_section(s, i) for i, s in enumerate(data.sections))
    footer_html = (
        f'\n<footer class="report-footer">'
        f"\n  <p>{html.escape(data.footer)}</p>"
        f"\n</footer>"
        if data.footer else ""
    )

    has_vc = graph_data is not None and bool(graph_data.get("nodes"))
    vc_panel  = _render_vc_panel(graph_data) if has_vc else f"<div class='vc-wrap'><p style='padding:3rem;color:var(--text-3);font-family:var(--font-m);font-size:.7rem'>No value chain data found. Run: company-research value-chain {html.escape(data.ticker)}</p></div>"
    src_panel = _render_sources_panel(sources_data or [])
    as_of     = data.metadata.get("As of", "<date>")
    qa_panel  = _render_qa_panel(data.ticker, qa_port, as_of=as_of)
    js_block  = _build_js(data.ticker, has_vc, qa_port)

    graph_json = json.dumps(graph_data or {}, ensure_ascii=False)
    title_esc  = f"{html.escape(data.company)} ({html.escape(data.ticker)}) — Research Report"
    src_count  = len(sources_data) if sources_data else 0

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title_esc}</title>
  <script src="https://d3js.org/d3.v7.min.js"></script>
  <style>
{_CSS}
  </style>
</head>
<body>
<script>
window.GRAPH_DATA = {graph_json};
</script>

<nav class="tab-nav">
  <button class="tab-btn active" data-tab="report">Report</button>
  <button class="tab-btn" data-tab="vc">Value Chain</button>
  <button class="tab-btn" data-tab="sources">Sources ({src_count})</button>
  <button class="tab-btn" data-tab="ask">Ask</button>
</nav>

<!-- ── Report ── -->
<div id="panel-report" class="tab-panel active">
<div class="report-wrap">

<header class="hero">
  <div class="hero-eyebrow">
    <span class="hero-ticker">{html.escape(data.ticker)}</span>
    <span class="hero-exchange">{html.escape(exchange)}</span>
  </div>
  <h1 class="hero-company">{html.escape(data.company)}</h1>
  <p class="hero-subtitle">{html.escape(data.subtitle)}</p>
  {meta_html}
</header>

{toc_html}

<div class="sections">
  {sections_html}
</div>

{footer_html}

</div>
</div>

<!-- ── Value Chain ── -->
<div id="panel-vc" class="tab-panel">
{vc_panel}
</div>

<!-- ── Sources ── -->
<div id="panel-sources" class="tab-panel">
{src_panel}
</div>

<!-- ── Ask ── -->
<div id="panel-ask" class="tab-panel">
{qa_panel}
</div>

<script>
{js_block}
</script>
</body>
</html>
"""


# ── public API ────────────────────────────────────────────────────────────────

def convert(
    md_path: Path,
    html_path: Path | None = None,
    qa_port: int = _QA_PORT_DEFAULT,
) -> Path:
    """Convert a report.md to HTML. Auto-detects value chain siblings in the same dir."""
    md_path = Path(md_path)
    run_dir = md_path.parent

    md_text    = md_path.read_text(encoding="utf-8")
    data       = parse_report(md_text)

    # Auto-detect sibling files from run directory
    graph_data: dict | None = None
    vc_graph_path = run_dir / "value_chain_graph.json"
    if vc_graph_path.exists():
        try:
            graph_data = json.loads(vc_graph_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    sources_data: list[dict] | None = None
    sources_path = run_dir / "sources.json"
    if sources_path.exists():
        try:
            sources_data = json.loads(sources_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    out = render_html(data, graph_data=graph_data, sources_data=sources_data, qa_port=qa_port)

    if html_path is None:
        html_path = md_path.with_suffix(".html")
    html_path = Path(html_path)
    html_path.write_text(out, encoding="utf-8")
    return html_path
