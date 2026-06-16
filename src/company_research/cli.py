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


@cli.command("to-html")
@click.argument("report_md", type=click.Path(exists=True))
@click.option(
    "--output",
    "output_html",
    default=None,
    type=click.Path(),
    help="Output HTML path. Defaults to report.html next to the input file.",
)
@click.pass_context
def to_html(ctx: click.Context, report_md: str, output_html: str | None) -> None:
    """Convert a report.md to a styled, self-contained HTML file."""
    from company_research.reporting.html_export import convert

    md_path = Path(report_md)
    html_path = Path(output_html) if output_html else None
    out = convert(md_path, html_path)
    console.print(f"[green]✓[/green] HTML report: {out}")


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
