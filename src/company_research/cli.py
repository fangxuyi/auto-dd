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
@click.pass_context
def analyze(
    ctx: click.Context,
    symbol: str,
    depth: str,
    as_of: str | None,
    lookback_years: int,
    output_dir: str,
) -> None:
    """Analyze a public company and produce a research report."""
    from company_research.pipeline import analyze as run_pipeline

    as_of_date = date.fromisoformat(as_of) if as_of else date.today()
    out = Path(output_dir)

    console.print(
        f"[bold]Analyzing[/bold] [cyan]{symbol.upper()}[/cyan] | "
        f"depth=[yellow]{depth}[/yellow] | as-of={as_of_date} | lookback={lookback_years}y"
    )

    try:
        run = run_pipeline(
            symbol=symbol,
            depth=depth,
            as_of=as_of_date,
            lookback_years=lookback_years,
            output_root=out,
        )
        out_dir = out / symbol.upper() / as_of_date.isoformat()
        console.print(f"\n[green]✓[/green] Run {run.status}. Outputs at: {out_dir}")
        _print_output_summary(out_dir)
    except Exception as e:
        console.print(f"[red]✗ Analysis failed:[/red] {e}")
        sys.exit(1)


@cli.command()
@click.argument("symbol")
@click.option("--output", "output_dir", default="./research", type=click.Path())
@click.pass_context
def update(ctx: click.Context, symbol: str, output_dir: str) -> None:
    """Fetch new sources and update an existing research run."""
    console.print(f"[yellow]Update mode not yet implemented (Milestone 4).[/yellow]")
    console.print(f"To re-run a full analysis: company-research analyze {symbol}")


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
@click.pass_context
def compare(ctx: click.Context, symbol: str, peers: tuple[str, ...]) -> None:
    """Compare a company against peers (Milestone 2+)."""
    console.print(f"[yellow]Compare mode not yet implemented (Milestone 2).[/yellow]")


def _print_output_summary(out_dir: Path) -> None:
    files = [
        "sources.json", "evidence.jsonl", "metrics.csv",
        "contradictions.json", "open_questions.json", "qa_report.json",
    ]
    console.print("\n[bold]Output files:[/bold]")
    for f in files:
        path = out_dir / f
        status = "[green]✓[/green]" if path.exists() else "[red]✗[/red]"
        console.print(f"  {status} {f}")
