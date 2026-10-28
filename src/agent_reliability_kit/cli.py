"""`arkit` CLI: run eval datasets and render scorecards.

  run        Run a .jsonl dataset against a target; gate CI on pass rates.
  template   Write a blank scorecard YAML.
  report     Render a scorecard as Markdown or a self-contained HTML page.
  diff       Per-dimension change between two scorecards.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from ruamel.yaml import YAML

from . import __version__
from .audit.html_report import render_html
from .audit.report import fmt_delta, render_markdown, score_deltas
from .audit.scorecard import DIMENSIONS, Scorecard
from .evals.datasets import Dataset
from .evals.harness import EvalHarness, EvalResult
from .evals.loss_analysis import cluster_failures
from .targets import load_target

app = typer.Typer(help="Agent Reliability Kit: evals and scorecards.", no_args_is_help=True)
console = Console()


def _print_version(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    _version: bool = typer.Option(
        False, "--version", callback=_print_version, is_eager=True, help="Print the version."
    ),
) -> None:
    pass


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


@app.command()
def run(
    dataset_path: Path = typer.Argument(..., exists=True, help="Path to a .jsonl dataset."),
    target: str = typer.Option(
        ...,
        "--target",
        "-t",
        help=(
            "dotted.path:callable that takes the input dict, or an http(s) URL the input "
            "is POSTed to as JSON (headers from AR_TARGET_HEADERS)."
        ),
    ),
    scorers_module: str = typer.Option(
        ..., "--scorers", "-s", help="dotted.path:NAME pointing at a list of Scorer instances."
    ),
    concurrency: int = typer.Option(4, "--concurrency", "-c"),
    fail_under: float = typer.Option(
        0.0, "--fail-under", help="Exit non-zero if the pass rate drops below this."
    ),
    trap_fail_under: float = typer.Option(
        0.0,
        "--trap-fail-under",
        help="Exit non-zero if any populated trap class's pass rate drops below this.",
    ),
    tag: str | None = typer.Option(None, "--tag", help="Only run cases with this tag."),
    analyze: bool = typer.Option(False, "--analyze", help="Cluster failures by signature."),
    analyze_model: str | None = typer.Option(
        None, "--analyze-model", help="dotted.path:callable (prompt -> text) to name clusters."
    ),
) -> None:
    """Run an eval dataset against a target."""
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())
    ds = Dataset.from_jsonl(dataset_path)
    try:
        target_fn = load_target(target)
    except (ImportError, AttributeError, ValueError) as e:
        raise typer.BadParameter(_load_hint(target, e), param_hint="--target") from e
    try:
        scorers = _import_attr(scorers_module)
    except (ImportError, AttributeError) as e:
        raise typer.BadParameter(_load_hint(scorers_module, e), param_hint="--scorers") from e
    console.print(f"[bold]Running[/bold] {len(ds)} cases from [cyan]{ds.name}[/cyan]")
    harness = EvalHarness(target=target_fn, scorers=scorers, concurrency=concurrency)
    result = harness.run(ds, tag=tag)
    _print_summary(result)
    if result.total and result.errored == result.total:
        console.print("[red]Every case errored, so nothing was scored. Check the target.[/red]")
        raise typer.Exit(code=1)

    if analyze:
        label_model = _import_attr(analyze_model) if analyze_model else None
        clusters = cluster_failures(result, label_model=label_model)
        if clusters:
            t = Table(title="Failure clusters")
            for col in ("Signature", "Count", "Theme / sample reason", "Cases"):
                t.add_column(col, overflow="fold")
            for c in clusters:
                t.add_row(c.signature, str(c.count), c.theme or c.sample_reason, ", ".join(c.case_ids[:8]))
            console.print(t)

    failing = result.trap_class_below(trap_fail_under) if trap_fail_under else []
    for tc in failing:
        console.print(
            f"[red]Trap class[/red] [bold]{tc.trap_class}[/bold] pass rate {tc.pass_rate:.2%} "
            f"below {trap_fail_under:.2%} ({tc.passed}/{tc.total})"
        )
    if result.pass_rate < fail_under:
        console.print(f"[red]Pass rate {result.pass_rate:.2%} below {fail_under:.2%}[/red]")
        raise typer.Exit(code=1)
    if failing:
        raise typer.Exit(code=1)


@app.command()
def template(out: Path = typer.Argument(..., dir_okay=False)) -> None:
    """Write a blank scorecard YAML with all 8 dimensions at score 0."""
    payload = {
        "client": "Team or company",
        "agent": "Agent name",
        "auditor": "",
        "scores": [
            {"key": d.key, "score": 0, "evidence": "", "recommendations": []} for d in DIMENSIONS
        ],
        "top_risks": [],
        "notes": "",
    }
    with out.open("w", encoding="utf-8") as f:
        _yaml().dump(payload, f)
    console.print(f"[green]Wrote[/green] {out}")


@app.command()
def report(
    scorecard_yaml: Path = typer.Argument(..., exists=True, dir_okay=False),
    previous_yaml: Path | None = typer.Option(
        None, "--previous", exists=True, dir_okay=False, help="Earlier scorecard to compare with."
    ),
    out: Path = typer.Option(
        Path("scorecard.md"), "--out", "-o", help="A .html path writes a self-contained page."
    ),
) -> None:
    """Render a scorecard as Markdown, or as HTML when --out ends in .html."""
    sc = _load(scorecard_yaml)
    previous = _load(previous_yaml) if previous_yaml else None
    render = render_html if out.suffix.lower() in (".html", ".htm") else render_markdown
    doc = render(scorecard=sc, previous=previous)
    out.write_text(doc, encoding="utf-8")
    console.print(f"[green]Wrote[/green] {out}")
    console.print(f"[bold]Overall:[/bold] {sc.overall():.2f} / 5.0 - [italic]{sc.verdict()}[/italic]")


@app.command()
def diff(
    previous_yaml: Path = typer.Argument(..., exists=True, dir_okay=False),
    current_yaml: Path = typer.Argument(..., exists=True, dir_okay=False),
) -> None:
    """Per-dimension change between two scorecards."""
    before, now = _load(previous_yaml), _load(current_yaml)
    deltas = score_deltas(now, before)
    t = Table(title=f"{now.agent}: {before.audited_at.date()} -> {now.audited_at.date()}")
    for col in ("Dimension", "Before", "Now", "Change"):
        t.add_column(col, justify="left" if col == "Dimension" else "right")
    b_key, n_key = before.by_key(), now.by_key()
    for d in DIMENSIONS:
        delta = deltas[d.key]
        t.add_row(
            d.name,
            str(b_key[d.key].score) if d.key in b_key else "-",
            str(n_key[d.key].score) if d.key in n_key else "-",
            fmt_delta(delta) if delta is not None else "-",
        )
    console.print(t)
    console.print(
        f"[bold]Overall:[/bold] {before.overall():.2f} -> {now.overall():.2f} "
        f"({now.overall() - before.overall():+.2f})"
    )


def _yaml() -> YAML:
    # Pure-Python YAML: installs on any Python version without a C compiler.
    y = YAML(typ="safe", pure=True)
    y.default_flow_style = False
    y.representer.sort_base_mapping_type_on_output = False  # keep template field order
    return y


def _load(path: Path) -> Scorecard:
    return Scorecard(**_yaml().load(path.read_text(encoding="utf-8")))


def _load_hint(spec: str, error: Exception) -> str:
    msg = f"can't load {spec!r}: {error}"
    if isinstance(error, ModuleNotFoundError) and error.name == spec.split(":")[0]:
        msg += f". Run arkit from the folder that holds {error.name}.py."
    return msg


def _import_attr(spec: str):
    if ":" not in spec:
        raise typer.BadParameter(f"Expected module:attr, got {spec!r}")
    mod_path, attr = spec.split(":", 1)
    return getattr(importlib.import_module(mod_path), attr)


def _print_summary(result: EvalResult) -> None:
    summary = Table(title=f"{result.dataset_name}@{result.dataset_version}")
    summary.add_column("Metric")
    summary.add_column("Value", justify="right")
    summary.add_row("Total", str(result.total))
    summary.add_row("Passed", f"[green]{result.passed}[/green]")
    summary.add_row("Failed", f"[yellow]{result.failed}[/yellow]")
    summary.add_row("Errored", f"[red]{result.errored}[/red]")
    summary.add_row("Pass rate", f"{result.pass_rate:.2%}")
    console.print(summary)

    if result.trap_coverage:
        t = Table(title="Trap-class coverage")
        t.add_column("Trap class")
        t.add_column("Cases", justify="right")
        t.add_column("Pass rate", justify="right")
        for tc in result.trap_coverage:
            t.add_row(tc.trap_class, str(tc.total), f"{tc.pass_rate:.0%} ({tc.passed}/{tc.total})")
        console.print(t)

    failures = [r for r in result.runs if not r.passed]
    if failures:
        t = Table(title="Failures (first 10)")
        t.add_column("Case")
        t.add_column("Reason", overflow="fold")
        for r in failures[:10]:
            reason = f"ERROR: {r.error}" if r.error else "; ".join(
                f"{s.name}={s.score:.2f}({s.reason})" for s in r.scores if not s.passed
            )
            t.add_row(r.case_id, reason)
        console.print(t)


if __name__ == "__main__":
    app()
