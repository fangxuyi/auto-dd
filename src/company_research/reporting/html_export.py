"""Convert auto-dd report.md files to self-contained styled HTML."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path


# ── regex constants ───────────────────────────────────────────────────────────

_UUID_RE = re.compile(
    r"\[([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\]"
)
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_META_LINE_RE = re.compile(r"^\*\*(.+?):\*\*\s*(.+)$")
_SECTION_HEADING_RE = re.compile(r"^##\s+(\d+)\.\s+(.+)$")

_CONC_KEYS: dict[str, str] = {
    "**Conclusion:**": "conclusion",
    "**Confidence:**": "confidence",
    "**Counterevidence:**": "counterevidence",
    "**What would change this conclusion:**": "what_would_change",
}

_CONF_CLASS: dict[str, str] = {
    "low": "low",
    "medium": "medium",
    "high": "high",
}


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
    ticker: str = ""
    subtitle: str = ""
    metadata: dict[str, str] = field(default_factory=dict)
    sections: list[SectionData] = field(default_factory=list)
    footer: str = ""


# ── inline markdown ───────────────────────────────────────────────────────────


def _inline_md(text: str) -> str:
    """HTML-escape then apply bold, italic, and citation transforms."""
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
            sec.body_paragraphs = _paragraphs_from_lines(lines[i + 1 :])
            return sec
    return None


def _parse_conclusion(text: str, sec: SectionData) -> None:
    current: str | None = None
    buf: list[str] = []

    def flush() -> None:
        if current is None or not buf:
            return
        value = " ".join(" ".join(l.split()) for l in buf if l.strip())
        if current == "conclusion":
            sec.conclusion = value
        elif current == "confidence":
            sec.confidence = value
        elif current == "counterevidence":
            sec.counterevidence = value
        elif current == "what_would_change":
            sec.what_would_change = value

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        matched = False
        for marker, key in _CONC_KEYS.items():
            if line.startswith(marker):
                flush()
                buf = []
                current = key
                rest = line[len(marker) :].strip()
                if rest:
                    buf.append(rest)
                matched = True
                break
        if not matched and current is not None:
            buf.append(line)

    flush()


def parse_report(md_text: str) -> ReportData:
    """Parse a report.md string into structured ReportData."""
    chunks = re.split(r"\n---\n", md_text)
    data = ReportData()
    if not chunks:
        return data

    data.company, data.ticker, data.subtitle, data.metadata = _parse_header(chunks[0])

    i = 1
    while i < len(chunks):
        chunk = chunks[i].strip()
        sec = _parse_section_body(chunk)
        if sec is not None:
            if i + 1 < len(chunks):
                nxt = chunks[i + 1].strip()
                if "**Conclusion:**" in nxt:
                    _parse_conclusion(nxt, sec)
                    i += 2
                else:
                    i += 1
            else:
                i += 1
            data.sections.append(sec)
        elif chunk.startswith("*") and not chunk.startswith("**"):
            data.footer = chunk.strip("*").strip()
            i += 1
        else:
            i += 1

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

/* Subtle grid overlay */
body::before {
  content:"";
  position:fixed;
  inset:0;
  background-image:
    linear-gradient(rgba(196,150,42,.018) 1px,transparent 1px),
    linear-gradient(90deg,rgba(196,150,42,.018) 1px,transparent 1px);
  background-size:64px 64px;
  pointer-events:none;
  z-index:0;
}

/* Gold top stripe */
body::after {
  content:"";
  position:fixed;
  top:0;left:0;right:0;
  height:2px;
  background:linear-gradient(90deg,var(--gold),rgba(196,150,42,0));
  z-index:1000;
}

.report-wrap {
  max-width:800px;
  margin:0 auto;
  padding:0 2.5rem 7rem;
  position:relative;
  z-index:1;
}

/* ── hero ── */
.hero {
  padding:5.5rem 0 3rem;
  border-bottom:1px solid var(--border);
}

.hero-eyebrow {
  display:flex;
  align-items:center;
  gap:0.9rem;
  margin-bottom:1.75rem;
}

.hero-ticker {
  font-family:var(--font-m);
  font-size:0.68rem;
  font-weight:500;
  letter-spacing:0.22em;
  text-transform:uppercase;
  color:var(--gold-l);
  background:var(--gold-d);
  border:1px solid rgba(196,150,42,.28);
  padding:0.22rem 0.7rem;
  border-radius:3px;
}

.hero-exchange {
  font-family:var(--font-m);
  font-size:0.62rem;
  color:var(--text-3);
  letter-spacing:0.1em;
  text-transform:uppercase;
}

.hero-company {
  font-family:var(--font-d);
  font-size:clamp(2.5rem,5.5vw,4rem);
  font-weight:500;
  letter-spacing:-0.01em;
  line-height:1.08;
  color:var(--text);
  margin-bottom:0.6rem;
}

.hero-subtitle {
  font-family:var(--font-d);
  font-size:1.15rem;
  color:var(--text-2);
  font-style:italic;
  margin-bottom:2.5rem;
}

/* ── metadata ── */
.meta-strip {
  display:flex;
  flex-wrap:wrap;
  gap:0.2rem 2.5rem;
  padding:1.25rem 0;
  border-top:1px solid var(--border-sub);
  border-bottom:1px solid var(--border-sub);
}

.meta-item {
  display:flex;
  flex-direction:column;
  gap:0.12rem;
}

.meta-key {
  font-family:var(--font-m);
  font-size:0.53rem;
  text-transform:uppercase;
  letter-spacing:0.14em;
  color:var(--text-3);
}

.meta-val {
  font-family:var(--font-m);
  font-size:0.72rem;
  color:var(--gold-l);
}

/* ── table of contents ── */
.toc {
  padding:2.5rem 0;
  border-bottom:1px solid var(--border);
}

.toc-label {
  font-family:var(--font-m);
  font-size:0.55rem;
  text-transform:uppercase;
  letter-spacing:0.18em;
  color:var(--text-3);
  margin-bottom:1rem;
}

.toc-list {
  list-style:none;
}

.toc-list li {
  border-bottom:1px solid var(--border-sub);
}

.toc-list a {
  display:flex;
  align-items:baseline;
  gap:0.85rem;
  text-decoration:none;
  color:var(--text-2);
  font-family:var(--font-d);
  font-size:1rem;
  padding:0.55rem 0;
  transition:color 0.15s, padding-left 0.15s;
}

.toc-list a:hover {
  color:var(--gold-l);
  padding-left:0.4rem;
}

.toc-num {
  font-family:var(--font-m);
  font-size:0.6rem;
  color:var(--gold);
  min-width:1.6rem;
  letter-spacing:0.05em;
}

/* ── sections ── */
.sections{padding-top:0.5rem}

.report-section {
  position:relative;
  padding:4.5rem 0 2.5rem;
  border-bottom:1px solid var(--border-sub);
  opacity:0;
  animation:rise 0.55s cubic-bezier(.22,.68,0,1.1) forwards;
}

@keyframes rise {
  from{opacity:0;transform:translateY(16px)}
  to  {opacity:1;transform:translateY(0)}
}

.section-numeral {
  position:absolute;
  top:2rem;
  left:-2rem;
  font-family:var(--font-d);
  font-size:9rem;
  font-weight:600;
  color:rgba(196,150,42,.045);
  line-height:1;
  pointer-events:none;
  user-select:none;
  z-index:0;
}

.section-head {
  position:relative;
  z-index:1;
  margin-bottom:1.85rem;
}

.section-index {
  font-family:var(--font-m);
  font-size:0.57rem;
  text-transform:uppercase;
  letter-spacing:0.18em;
  color:var(--gold);
  margin-bottom:0.35rem;
}

.section-title {
  font-family:var(--font-d);
  font-size:1.85rem;
  font-weight:500;
  color:var(--text);
  line-height:1.15;
}

/* ── body text ── */
.section-body {
  position:relative;
  z-index:1;
}

.section-body p {
  margin-bottom:1.1rem;
  color:var(--text);
  font-size:1rem;
}

.section-body p:last-child{margin-bottom:0}

/* ── inline citations ── */
cite.cit {
  font-style:normal;
  font-family:var(--font-m);
  font-size:0.56em;
  vertical-align:super;
  line-height:0;
  color:var(--gold);
  background:var(--gold-d);
  border:1px solid rgba(196,150,42,.22);
  padding:0 3px;
  border-radius:2px;
  cursor:help;
  position:relative;
  white-space:nowrap;
  transition:background 0.15s;
  margin-left:1px;
  text-decoration:none;
}

cite.cit:hover{background:var(--gold-glow)}

cite.cit::after {
  content:attr(title);
  position:absolute;
  bottom:calc(100% + 5px);
  left:50%;
  transform:translateX(-50%);
  background:var(--surface-hi);
  border:1px solid var(--border);
  color:var(--text-2);
  font-size:0.78rem;
  padding:3px 7px;
  border-radius:3px;
  white-space:nowrap;
  opacity:0;
  pointer-events:none;
  transition:opacity 0.15s 0.08s;
  z-index:200;
}

cite.cit:hover::after{opacity:1}

/* ── analysis blocks ── */
.section-analysis {
  margin-top:2.75rem;
  position:relative;
  z-index:1;
}

.conclusion-block {
  padding:1.5rem 1.5rem 1.5rem 1.85rem;
  border-left:3px solid var(--gold);
  background:var(--gold-d);
  border-radius:0 6px 6px 0;
  margin-bottom:0.7rem;
}

.conclusion-header {
  display:flex;
  align-items:center;
  gap:0.75rem;
  margin-bottom:0.8rem;
  flex-wrap:wrap;
}

.block-eyebrow {
  font-family:var(--font-m);
  font-size:0.57rem;
  text-transform:uppercase;
  letter-spacing:0.16em;
  color:var(--gold-l);
}

.conf-badge {
  display:inline-flex;
  align-items:center;
  padding:0.15rem 0.55rem;
  border-radius:2px;
  font-family:var(--font-m);
  font-size:0.58rem;
  font-weight:500;
  letter-spacing:0.06em;
  text-transform:uppercase;
}

.conf-badge.low    {background:var(--amber-d);color:var(--amber-l);border:1px solid rgba(212,144,10,.3)}
.conf-badge.medium {background:var(--blue-d); color:var(--blue-l); border:1px solid rgba(74,132,196,.3)}
.conf-badge.high   {background:var(--green-d);color:var(--green-l);border:1px solid rgba(58,158,114,.3)}

.conclusion-block p {
  font-size:0.97rem;
  color:var(--text);
  line-height:1.72;
}

.detail-block {
  padding:1.1rem 1.25rem 1.1rem 1.6rem;
  border-left:2px solid;
  border-radius:0 4px 4px 0;
  margin-bottom:0.6rem;
}

.detail-block.cevid {
  border-color:var(--blue);
  background:var(--blue-d);
}

.detail-block.change {
  border-color:var(--green);
  background:var(--green-d);
}

.detail-eyebrow {
  font-family:var(--font-m);
  font-size:0.53rem;
  text-transform:uppercase;
  letter-spacing:0.16em;
  margin-bottom:0.5rem;
}

.cevid  .detail-eyebrow{color:var(--blue-l)}
.change .detail-eyebrow{color:var(--green-l)}

.detail-block p {
  font-size:0.9rem;
  color:var(--text-2);
  line-height:1.68;
}

/* ── footer ── */
.report-footer {
  padding:3rem 0 0;
  text-align:center;
}

.report-footer p {
  font-family:var(--font-d);
  font-style:italic;
  font-size:0.88rem;
  color:var(--text-3);
}

/* ── print ── */
@media print {
  body{background:#fff;color:#111;font-size:11pt}
  body::before,body::after{display:none}
  .report-wrap{max-width:100%;padding:0}
  .hero{padding:1rem 0}
  .report-section{page-break-inside:avoid;animation:none !important;opacity:1 !important}
  .section-numeral{display:none}
  cite.cit::after{display:none}
  .toc{display:none}
  .meta-strip,.conclusion-block,.detail-block{border-color:#ccc !important;background:#f9f9f9 !important}
  .conf-badge{border:1px solid #aaa !important;background:#eee !important;color:#333 !important}
}

@media(max-width:600px){
  body{font-size:15px}
  .report-wrap{padding:0 1.25rem 4rem}
  .section-numeral{font-size:5.5rem;left:-0.5rem}
  .hero{padding:3.5rem 0 2rem}
  .hero-company{font-size:2.2rem}
}
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

    body_html = "\n".join(
        f"    <p>{_inline_md(p)}</p>" for p in sec.body_paragraphs
    )

    analysis_html = ""
    if sec.conclusion or sec.counterevidence or sec.what_would_change:
        conf_lower = sec.confidence.lower()
        conf_cls = _CONF_CLASS.get(conf_lower, "medium")
        conf_badge = ""
        if sec.confidence:
            conf_badge = (
                f'<span class="conf-badge {conf_cls}">'
                f"{html.escape(sec.confidence)} confidence</span>"
            )

        conc_p = f"<p>{_inline_md(sec.conclusion)}</p>" if sec.conclusion else ""

        cevid_html = ""
        if sec.counterevidence:
            cevid_html = (
                f'\n  <div class="detail-block cevid">'
                f'\n    <div class="detail-eyebrow">Counterevidence</div>'
                f"\n    <p>{_inline_md(sec.counterevidence)}</p>"
                f"\n  </div>"
            )

        change_html = ""
        if sec.what_would_change:
            change_html = (
                f'\n  <div class="detail-block change">'
                f'\n    <div class="detail-eyebrow">What would change this conclusion</div>'
                f"\n    <p>{_inline_md(sec.what_would_change)}</p>"
                f"\n  </div>"
            )

        analysis_html = (
            f'\n<div class="section-analysis">'
            f'\n  <div class="conclusion-block">'
            f'\n    <div class="conclusion-header">'
            f'\n      <span class="block-eyebrow">Conclusion</span>'
            f"\n      {conf_badge}"
            f"\n    </div>"
            f"\n    {conc_p}"
            f"\n  </div>"
            f"{cevid_html}"
            f"{change_html}"
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
        f'\n  <div class="section-body">'
        f"\n{body_html}"
        f"\n  </div>"
        f"{analysis_html}"
        f"\n</section>"
    )


def render_html(data: ReportData) -> str:
    """Render ReportData to a complete self-contained HTML string."""
    exchange = data.metadata.get("Primary listing", "")
    meta_html = _render_meta(data.metadata)
    toc_html = _render_toc(data.sections)
    sections_html = "\n".join(
        _render_section(s, i) for i, s in enumerate(data.sections)
    )
    footer_html = (
        f'\n<footer class="report-footer">'
        f"\n  <p>{html.escape(data.footer)}</p>"
        f"\n</footer>"
        if data.footer
        else ""
    )

    title_esc = f"{html.escape(data.company)} ({html.escape(data.ticker)}) — Research Report"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title_esc}</title>
  <style>
{_CSS}
  </style>
</head>
<body>
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
</body>
</html>
"""


# ── public API ────────────────────────────────────────────────────────────────


def convert(md_path: Path, html_path: Path | None = None) -> Path:
    """Convert a report.md to HTML. Writes adjacent .html file by default."""
    md_text = md_path.read_text(encoding="utf-8")
    data = parse_report(md_text)
    out = render_html(data)
    if html_path is None:
        html_path = md_path.with_suffix(".html")
    html_path.write_text(out, encoding="utf-8")
    return html_path
