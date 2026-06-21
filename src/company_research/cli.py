from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path

import click
from rich.console import Console
from rich.logging import RichHandler

console = Console()


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """Public-company research pipeline."""
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    _setup_logging(verbose)


@cli.command()
@click.argument("symbol")
@click.option("--depth", default="standard", type=click.Choice(["quick", "standard", "deep"]))
@click.option("--as-of", "as_of", default=None, help="Analysis date (YYYY-MM-DD). Defaults to today.")
@click.option("--lookback-years", "lookback_years", default=5, type=int)
@click.option("--output", "output_dir", default="./research", type=click.Path())
@click.option("--rag-top-k", "rag_top_k", default=None, type=int, help="Override profile rag_top_k (chunks per section).")
@click.option("--dry-run", "dry_run", is_flag=True, help="Write prompts to files instead of calling the API.")
@click.pass_context
def analyze(
    ctx: click.Context,
    symbol: str,
    depth: str,
    as_of: str | None,
    lookback_years: int,
    output_dir: str,
    rag_top_k: int | None,
    dry_run: bool,
) -> None:
    """Analyze a public company and produce a research report."""
    from company_research.pipeline import analyze as run_pipeline

    as_of_date = date.fromisoformat(as_of) if as_of else date.today()
    out = Path(output_dir)

    mode_tag = " [yellow][dry-run][/yellow]" if dry_run else ""
    rag_tag = f" | rag-top-k={rag_top_k}" if rag_top_k is not None else ""
    console.print(
        f"[bold]Analyzing[/bold] [cyan]{symbol.upper()}[/cyan] | "
        f"depth=[yellow]{depth}[/yellow] | as-of={as_of_date} | lookback={lookback_years}y"
        f"{rag_tag}{mode_tag}"
    )

    try:
        run = run_pipeline(
            symbol=symbol,
            depth=depth,
            as_of=as_of_date,
            lookback_years=lookback_years,
            output_root=out,
            dry_run=dry_run,
            rag_top_k=rag_top_k,
        )
        out_dir = out / symbol.upper() / as_of_date.isoformat()
        console.print(f"\n[green]✓[/green] Run {run.status}. Outputs at: {out_dir}")
        if dry_run:
            prompts_dir = out_dir / "prompts"
            prompt_files = sorted(prompts_dir.glob("*.txt")) if prompts_dir.exists() else []
            console.print(f"\n[bold]Dry-run prompts[/bold] ({len(prompt_files)} files at {prompts_dir}):")
            for p in prompt_files:
                console.print(f"  [cyan]{p.name}[/cyan]  ({p.stat().st_size:,} bytes)")
        else:
            _print_output_summary(out_dir)
    except Exception as e:
        console.print(f"[red]✗ Analysis failed:[/red] {e}")
        sys.exit(1)


@cli.command("report")
@click.argument("symbol")
@click.option("--depth", default="standard", type=click.Choice(["quick", "standard", "deep"]))
@click.option("--as-of", "as_of", default=None, help="Analysis date (YYYY-MM-DD). Defaults to today.")
@click.option("--lookback-years", "lookback_years", default=5, type=int)
@click.option("--output", "output_dir", default="./research", type=click.Path())
@click.option("--rag-top-k", "rag_top_k", default=None, type=int, help="Override profile rag_top_k.")
@click.option("--dry-run", "dry_run", is_flag=True, help="Write prompts to files instead of calling the API.")
@click.pass_context
def report_cmd(
    ctx: click.Context,
    symbol: str,
    depth: str,
    as_of: str | None,
    lookback_years: int,
    output_dir: str,
    rag_top_k: int | None,
    dry_run: bool,
) -> None:
    """Generate a report from the existing RAG — no source fetching.

    Skips Steps 1-4 (entity resolution / source fetch / indexing) and runs
    fact extraction → section analysis → report using whatever is already in
    the vector store for SYMBOL.  Useful for regenerating a report after
    editing prompts or changing analysis depth without re-downloading sources.

    \b
    Example:
        company-research report AAPL --depth deep
    """
    from company_research.pipeline import report_only

    as_of_date = date.fromisoformat(as_of) if as_of else date.today()
    out = Path(output_dir)

    mode_tag = " [yellow][dry-run][/yellow]" if dry_run else ""
    console.print(
        f"[bold]Report (RAG-only)[/bold] [cyan]{symbol.upper()}[/cyan] | "
        f"depth=[yellow]{depth}[/yellow] | as-of={as_of_date}{mode_tag}"
    )

    try:
        run = report_only(
            symbol=symbol,
            depth=depth,
            as_of=as_of_date,
            lookback_years=lookback_years,
            output_root=out,
            dry_run=dry_run,
            rag_top_k=rag_top_k,
        )
        out_dir = out / symbol.upper() / as_of_date.isoformat()
        console.print(f"\n[green]✓[/green] Run {run.status}. Outputs at: {out_dir}")
        if dry_run:
            prompts_dir = out_dir / "prompts"
            prompt_files = sorted(prompts_dir.glob("*.txt")) if prompts_dir.exists() else []
            console.print(f"\n[bold]Dry-run prompts[/bold] ({len(prompt_files)} files at {prompts_dir}):")
            for p in prompt_files:
                console.print(f"  [cyan]{p.name}[/cyan]  ({p.stat().st_size:,} bytes)")
        else:
            _print_output_summary(out_dir)
    except Exception as e:
        console.print(f"[red]✗ Report failed:[/red] {e}")
        sys.exit(1)


@cli.command()
@click.argument("symbol")
@click.option("--depth", default="standard", type=click.Choice(["quick", "standard", "deep"]))
@click.option("--as-of", "as_of", default=None, help="Analysis date (YYYY-MM-DD). Defaults to today.")
@click.option("--lookback-years", "lookback_years", default=5, type=int)
@click.option("--output", "output_dir", default="./research", type=click.Path())
@click.option("--rag-top-k", "rag_top_k", default=None, type=int)
@click.option("--dry-run", "dry_run", is_flag=True)
@click.pass_context
def update(
    ctx: click.Context,
    symbol: str,
    depth: str,
    as_of: str | None,
    lookback_years: int,
    output_dir: str,
    rag_top_k: int | None,
    dry_run: bool,
) -> None:
    """Fetch new sources, update an existing run, and produce a diff report."""
    from company_research.pipeline_update import update as run_update
    from company_research.storage.export import export_diff

    as_of_date = date.fromisoformat(as_of) if as_of else date.today()
    out = Path(output_dir)
    mode_tag = " [yellow][dry-run][/yellow]" if dry_run else ""
    console.print(
        f"[bold]Updating[/bold] [cyan]{symbol.upper()}[/cyan] | "
        f"depth=[yellow]{depth}[/yellow] | as-of={as_of_date}{mode_tag}"
    )

    try:
        new_run, diff = run_update(
            symbol=symbol,
            depth=depth,
            as_of=as_of_date,
            lookback_years=lookback_years,
            output_root=out,
            dry_run=dry_run,
            rag_top_k=rag_top_k,
        )
        out_dir = out / symbol.upper() / as_of_date.isoformat()
        export_diff(diff, out_dir)

        changed = [c for c in diff.changed_conclusions if c.change_type == "changed"]
        console.print(f"\n[green]✓[/green] Update complete — {out_dir}")
        console.print(
            f"  new sources: {diff.new_sources_count} | "
            f"new facts: {len(diff.new_facts)} | "
            f"changed conclusions: {len(changed)} | "
            f"metric changes: {len(diff.changed_metrics)}"
        )
    except Exception as e:
        console.print(f"[red]✗ Update failed:[/red] {e}")
        sys.exit(1)


@cli.command()
@click.argument("run_dir", type=click.Path(exists=True))
@click.pass_context
def validate(ctx: click.Context, run_dir: str) -> None:
    """Validate the QA report for a completed research run."""
    import json
    qa_path = Path(run_dir) / "qa_report.json"
    if not qa_path.exists():
        console.print(f"[red]No qa_report.json found at {run_dir}[/red]")
        sys.exit(1)

    qa = json.loads(qa_path.read_text())
    if qa.get("passed"):
        console.print(f"[green]✓ QA passed[/green] — {run_dir}")
    else:
        console.print(f"[red]✗ QA failed[/red] — {run_dir}")
        for failure in qa.get("critical_failures", []):
            console.print(f"  [red]•[/red] {failure}")
    for warning in qa.get("warnings", []):
        console.print(f"  [yellow]⚠[/yellow] {warning}")


@cli.command()
@click.argument("symbol")
@click.argument("peers", nargs=-1, required=True)
@click.option("--depth", default="quick", type=click.Choice(["quick", "standard", "deep"]))
@click.option("--as-of", "as_of", default=None, help="Analysis date (YYYY-MM-DD).")
@click.option("--output", "output_dir", default="./research", type=click.Path())
@click.option("--dry-run", "dry_run", is_flag=True)
@click.pass_context
def compare(
    ctx: click.Context,
    symbol: str,
    peers: tuple[str, ...],
    depth: str,
    as_of: str | None,
    output_dir: str,
    dry_run: bool,
) -> None:
    """Compare a company against one or more peers side-by-side."""
    from company_research.pipeline_compare import compare as run_compare
    from company_research.storage.export import export_compare

    as_of_date = date.fromisoformat(as_of) if as_of else date.today()
    out = Path(output_dir)
    symbols = [symbol.upper()] + [p.upper() for p in peers]
    console.print(f"[bold]Comparing[/bold] {' vs '.join(symbols)} | depth={depth} | as-of={as_of_date}")

    try:
        result = run_compare(
            symbols=symbols,
            output_root=out,
            depth=depth,
            as_of=as_of_date,
            dry_run=dry_run,
        )
        syms_tag = "_".join(symbols)
        compare_dir = out / "comparisons"
        export_compare(result, compare_dir)
        console.print(f"[green]✓[/green] Comparison written to {compare_dir}/compare_{syms_tag}.md")
    except Exception as e:
        console.print(f"[red]✗ Compare failed:[/red] {e}")
        sys.exit(1)


@cli.command("value-chain")
@click.argument("symbol")
@click.option("--depth", default="standard", type=click.Choice(["quick", "standard", "deep"]))
@click.option("--as-of", "as_of", default=None, help="Analysis date (YYYY-MM-DD).")
@click.option("--output", "output_dir", default="./research", type=click.Path())
@click.option("--template", "template_name", default=None, help="Industry template override.")
@click.pass_context
def value_chain(
    ctx: click.Context,
    symbol: str,
    depth: str,
    as_of: str | None,
    output_dir: str,
    template_name: str | None,
) -> None:
    """Map a company's upstream/downstream value chain from EDGAR evidence."""
    from company_research.pipeline_value_chain import run_value_chain

    as_of_date = date.fromisoformat(as_of) if as_of else date.today()
    out = Path(output_dir)
    console.print(
        f"[bold]Value Chain[/bold] [cyan]{symbol.upper()}[/cyan] | "
        f"depth={depth} | as-of={as_of_date}"
    )

    try:
        result = run_value_chain(
            symbol=symbol,
            depth=depth,
            as_of=as_of_date,
            output_root=out,
            template_name=template_name,
        )
        out_dir = out / symbol.upper() / as_of_date.isoformat()
        console.print(f"\n[green]✓[/green] Value chain complete — {out_dir}")
        console.print(
            f"  template: {result['template']} | layers: {result['layers']} | "
            f"candidates: {result['candidates_discovered']} | "
            f"resolved: {result['candidates_resolved']} | "
            f"relationships: {result['relationships']} | "
            f"graph nodes: {result['graph_nodes']} | confirmed edges: {result['confirmed_edges']}"
        )
        if not result["qa_passed"]:
            for failure in result["qa_failures"]:
                console.print(f"  [yellow]⚠[/yellow] QA: {failure}")
    except RuntimeError as e:
        console.print(f"[red]✗[/red] {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]✗ Value chain failed:[/red] {e}")
        sys.exit(1)


@cli.command("relationships")
@click.argument("symbol")
@click.option("--type", "rel_type", default=None, help="Filter by relationship type (e.g. SUPPLIES).")
@click.option("--status", default=None, help="Filter by status (e.g. confirmed_direct).")
@click.option("--output", "output_dir", default="./research", type=click.Path())
@click.pass_context
def relationships(
    ctx: click.Context,
    symbol: str,
    rel_type: str | None,
    status: str | None,
    output_dir: str,
) -> None:
    """List value chain relationships for a company."""
    import json
    from company_research.storage.database import Database

    db = Database(Path(output_dir) / "research.db")
    run = db.get_latest_run(symbol)
    if run is None:
        console.print(f"[red]No run found for {symbol}. Run value-chain first.[/red]")
        sys.exit(1)

    rels = db.get_vc_relationships(run["run_id"])
    if rel_type:
        rels = [r for r in rels if r.get("relationship_type") == rel_type.upper()]
    if status:
        rels = [r for r in rels if r.get("current_status") == status]

    console.print(f"\n[bold]Relationships for {symbol.upper()}[/bold] ({len(rels)} found)\n")
    for r in rels:
        conf = r.get("confidence", "unknown")
        rtype = r.get("relationship_type", "")
        cur_status = r.get("current_status", "")
        console.print(f"  [{conf}] {rtype} — {cur_status}")


@cli.command("graph")
@click.argument("symbol")
@click.option("--format", "fmt", default="json", type=click.Choice(["json", "csv"]))
@click.option("--output", "output_dir", default="./research", type=click.Path())
@click.option("--as-of", "as_of", default=None)
@click.pass_context
def graph(
    ctx: click.Context,
    symbol: str,
    fmt: str,
    output_dir: str,
    as_of: str | None,
) -> None:
    """Show or export the value chain graph for a company."""
    as_of_date = date.fromisoformat(as_of) if as_of else date.today()
    out_dir = Path(output_dir) / symbol.upper() / as_of_date.isoformat()
    graph_json = out_dir / "value_chain_graph.json"
    nodes_csv = out_dir / "value_chain_nodes.csv"
    edges_csv = out_dir / "value_chain_edges.csv"

    if fmt == "json":
        if not graph_json.exists():
            console.print(f"[red]No graph found at {graph_json}. Run value-chain first.[/red]")
            sys.exit(1)
        console.print(graph_json.read_text())
    else:
        for csv_path in (nodes_csv, edges_csv):
            if csv_path.exists():
                console.print(f"\n[bold]{csv_path.name}[/bold]")
                console.print(csv_path.read_text())


@cli.command("to-html")
@click.argument("report_md", type=click.Path(exists=True))
@click.option(
    "--output",
    "output_html",
    default=None,
    type=click.Path(),
    help="Output HTML path. Defaults to report.html next to the input file.",
)
@click.option("--port", default=7234, help="RAG server port shown in HTML instructions.")
@click.pass_context
def to_html(ctx: click.Context, report_md: str, output_html: str | None, port: int) -> None:
    """Convert a report.md to a styled, self-contained HTML file.

    Automatically embeds value_chain_graph.json if found in the same directory.
    The HTML includes a Q&A tab — start the RAG server first with:

        company-research serve <report_md> [--port PORT]
    """
    from company_research.reporting.html_export import convert

    md_path = Path(report_md)
    html_path = Path(output_html) if output_html else None
    out = convert(md_path, html_path, qa_port=port)
    console.print(f"[green]✓[/green] HTML report: {out}")
    console.print(
        f"\n[dim]To enable Q&A: [/dim][bold]company-research serve {report_md} --port {port}[/bold]"
    )


@cli.command("serve")
@click.argument("report_md", type=click.Path(exists=True))
@click.option("--port", default=7234, help="Port for the local RAG server.")
@click.option("--no-browser", is_flag=True, help="Don't open the HTML file in a browser.")
@click.pass_context
def serve_cmd(ctx: click.Context, report_md: str, port: int, no_browser: bool) -> None:
    """Start a local RAG Q&A server for an auto-dd research run.

    The server answers questions by retrieving from the run's vector store and
    calling Claude. The HTML report's Ask tab connects to this server.

    \b
    Example:
        company-research serve research/AAPL/2026-06-16/report.md
    """
    import time
    import webbrowser
    from dotenv import load_dotenv

    load_dotenv()

    from company_research.reporting.serve import RagServer

    md_path = Path(report_md)
    run_dir = md_path.parent
    html_path = md_path.with_suffix(".html")

    # Auto-generate HTML if missing
    if not html_path.exists():
        from company_research.reporting.html_export import convert
        html_path = convert(md_path, qa_port=port)
        console.print(f"[green]✓[/green] Generated HTML: {html_path}")

    symbol = run_dir.parent.name  # research/<SYMBOL>/<date>/report.md

    server = RagServer(run_dir=run_dir, symbol=symbol, port=port)
    server.start_background()

    console.print(f"[green]✓[/green] RAG server running at [bold]http://127.0.0.1:{port}[/bold]")
    console.print(f"  Symbol : [bold]{symbol}[/bold]")
    console.print(f"  Run dir: {run_dir}")
    console.print(f"  HTML   : {html_path}")
    console.print("\nPress [bold]Ctrl-C[/bold] to stop.\n")

    if not no_browser:
        time.sleep(0.4)
        webbrowser.open(html_path.resolve().as_uri())

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        console.print("\n[dim]Server stopped.[/dim]")


@cli.command("research")
@click.argument("symbol")
@click.option("--depth", default="standard", type=click.Choice(["quick", "standard", "deep"]))
@click.option("--as-of", "as_of", default=None, help="Analysis date (YYYY-MM-DD). Defaults to today.")
@click.option("--lookback-years", "lookback_years", default=5, type=int)
@click.option("--output", "output_dir", default="./research", type=click.Path())
@click.option("--rag-top-k", "rag_top_k", default=None, type=int, help="Override profile rag_top_k (chunks per section).")
@click.option("--port", default=7234, help="RAG server port.")
@click.option("--no-value-chain", "skip_vc", is_flag=True, help="Skip value chain step.")
@click.option("--no-serve", "skip_serve", is_flag=True, help="Generate HTML but don't start the RAG server.")
@click.pass_context
def research_cmd(
    ctx: click.Context,
    symbol: str,
    depth: str,
    as_of: str | None,
    lookback_years: int,
    output_dir: str,
    rag_top_k: int | None,
    port: int,
    skip_vc: bool,
    skip_serve: bool,
) -> None:
    """Full pipeline: analyze → value-chain → HTML → serve.

    \b
    Example:
        company-research research AAPL
        company-research research AAPL --depth deep --no-serve
    """
    import time
    import webbrowser
    from dotenv import load_dotenv

    load_dotenv()

    from company_research.pipeline import analyze as run_pipeline
    from company_research.pipeline_value_chain import run_value_chain
    from company_research.reporting.html_export import convert
    from company_research.reporting.serve import RagServer

    as_of_date = date.fromisoformat(as_of) if as_of else date.today()
    out = Path(output_dir)
    out_dir = out / symbol.upper() / as_of_date.isoformat()
    total_steps = 3 if skip_serve else 4

    # ── Step 1: Analyze ──────────────────────────────────────────────────────
    console.print(
        f"\n[bold cyan]╔══ Step 1/{total_steps} — Analyze[/bold cyan] "
        f"[cyan]{symbol.upper()}[/cyan] | depth={depth} | as-of={as_of_date}"
    )
    try:
        run_pipeline(
            symbol=symbol,
            depth=depth,
            as_of=as_of_date,
            lookback_years=lookback_years,
            output_root=out,
            rag_top_k=rag_top_k,
            dry_run=False,
        )
        console.print(f"[green]✓[/green] Analysis complete → {out_dir}")
    except Exception as e:
        console.print(f"[red]✗ Analysis failed:[/red] {e}")
        sys.exit(1)

    # ── Step 2: Value chain ──────────────────────────────────────────────────
    if not skip_vc:
        console.print(f"\n[bold cyan]╠══ Step 2/{total_steps} — Value Chain[/bold cyan] {symbol.upper()}")
        try:
            result = run_value_chain(
                symbol=symbol,
                depth=depth,
                as_of=as_of_date,
                output_root=out,
            )
            console.print(
                f"[green]✓[/green] Value chain complete "
                f"({result['graph_nodes']} nodes, {result['confirmed_edges']} edges)"
            )
        except Exception as e:
            console.print(f"[yellow]⚠ Value chain failed (continuing):[/yellow] {e}")
    else:
        console.print(f"\n[dim]╠══ Step 2/{total_steps} — Value Chain (skipped)[/dim]")

    # ── Step 3: HTML ─────────────────────────────────────────────────────────
    console.print(f"\n[bold cyan]╠══ Step 3/{total_steps} — HTML[/bold cyan]")
    md_path = out_dir / "report.md"
    html_path = convert(md_path, qa_port=port)
    console.print(f"[green]✓[/green] HTML → {html_path}")

    # ── Step 4: Serve ────────────────────────────────────────────────────────
    if skip_serve:
        console.print(f"\n[bold green]╚══ Done.[/bold green] {symbol.upper()} · {as_of_date}")
        console.print(f"    Report : {md_path}")
        console.print(f"    HTML   : {html_path}")
        console.print(
            f"\n[dim]To start Q&A:[/dim] "
            f"[bold]company-research serve {md_path} --port {port}[/bold]"
        )
        webbrowser.open(html_path.resolve().as_uri())
        return

    console.print(f"\n[bold cyan]╚══ Step 4/{total_steps} — Serve[/bold cyan]")
    server = RagServer(run_dir=out_dir, symbol=symbol, port=port)
    server.start_background()
    console.print(f"[green]✓[/green] RAG server at [bold]http://127.0.0.1:{port}[/bold]")
    console.print(f"    Report : {md_path}")
    console.print(f"    HTML   : {html_path}")
    console.print("\nPress [bold]Ctrl-C[/bold] to stop.\n")

    time.sleep(0.4)
    webbrowser.open(html_path.resolve().as_uri())

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        console.print("\n[dim]Server stopped.[/dim]")


def _print_output_summary(out_dir: Path) -> None:
    files = [
        "report.md", "sources.json", "evidence.jsonl", "metrics.csv",
        "contradictions.json", "open_questions.json", "qa_report.json",
        "run_flow.json", "monitoring.json", "peers.json",
    ]
    console.print("\n[bold]Output files:[/bold]")
    for f in files:
        path = out_dir / f
        status = "[green]✓[/green]" if path.exists() else "[red]✗[/red]"
        console.print(f"  {status} {f}")
