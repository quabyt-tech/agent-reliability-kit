"""Render an audit report from Scorecard + repo signals + trace findings."""

from __future__ import annotations

from io import StringIO

from .scorecard import DIMENSIONS, Scorecard, TraceFinding


def render_markdown(
    *,
    scorecard: Scorecard,
    repo_signals: dict | None = None,
    trace_findings: list[TraceFinding] | None = None,
    previous: Scorecard | None = None,
) -> str:
    """Render the audit deliverable as a single Markdown document.

    Drop-in ready for the Day-10 readout. Use Pandoc to convert to PDF. With
    `previous` (last month's scorecard, or the audit's) a change column is added.
    """
    out = StringIO()
    w = out.write

    w(f"# Reliability Audit — {scorecard.client}\n\n")
    w(f"- **Agent:** {scorecard.agent}\n")
    w(f"- **Auditor:** {scorecard.auditor}\n")
    w(f"- **Date:** {scorecard.audited_at.date().isoformat()}\n")
    w(f"- **Overall score:** **{scorecard.overall():.2f} / 5.0** — _{scorecard.verdict()}_\n")
    if previous:
        w(
            f"- **Change since {previous.audited_at.date().isoformat()}:** "
            f"{scorecard.overall() - previous.overall():+.2f} (was {previous.overall():.2f})\n"
        )
    w("\n")

    w("## Scorecard\n\n")
    deltas = score_deltas(scorecard, previous) if previous else {}
    if previous:
        w("| Dimension | Score | Change | Weight | Evidence |\n")
        w("| --- | ---: | ---: | ---: | --- |\n")
    else:
        w("| Dimension | Score | Weight | Evidence |\n")
        w("| --- | ---: | ---: | --- |\n")
    by_key = scorecard.by_key()
    for d in DIMENSIONS:
        s = by_key.get(d.key)
        score = f"{s.score} / 5" if s else "—"
        evidence = (s.evidence if s else "*(not scored)*").replace("\n", " ")
        change = f" {fmt_delta(deltas.get(d.key))} |" if previous else ""
        w(f"| {d.name} | {score} |{change} {int(d.weight * 100)}% | {evidence} |\n")
    w("\n")

    if scorecard.top_risks:
        w("## Top risks\n\n")
        for i, r in enumerate(scorecard.top_risks, 1):
            w(f"{i}. {r}\n")
        w("\n")

    w("## Per-dimension findings\n\n")
    for d in DIMENSIONS:
        s = by_key.get(d.key)
        if s is None:
            continue
        w(f"### {d.name} — {s.score} / 5\n\n")
        w(f"_{d.description}_\n\n")
        if s.evidence:
            w(f"**Evidence:** {s.evidence}\n\n")
        if s.recommendations:
            w("**Recommendations:**\n\n")
            for r in s.recommendations:
                w(f"- {r}\n")
            w("\n")

    if trace_findings:
        w("## Trace findings\n\n")
        for f in trace_findings:
            w(f"### [{f.severity}] {f.name} ({f.count})\n\n")
            w(f"{f.description}\n\n")
            if f.sample_trace_ids:
                w(f"Sample trace IDs: `{', '.join(f.sample_trace_ids)}`\n\n")
            if f.metadata:
                w("```\n")
                for k, v in f.metadata.items():
                    w(f"{k}: {v}\n")
                w("```\n\n")

    if repo_signals:
        w("## Repo signals\n\n")
        w("Static patterns surfaced during code review. Not a verdict — pointers for the auditor.\n\n")
        matched = repo_signals.get("matched", {})
        if matched:
            w("| Signal | Files |\n| --- | --- |\n")
            for name, files in sorted(matched.items()):
                shown = ", ".join(f"`{f}`" for f in files[:5])
                more = f" _(+{len(files) - 5} more)_" if len(files) > 5 else ""
                w(f"| {name} | {shown}{more} |\n")
            w("\n")
        notes = repo_signals.get("notes", [])
        if notes:
            w("**Notes:**\n\n")
            for n in notes:
                w(f"- {n}\n")
            w("\n")

    if scorecard.notes:
        w("## Auditor notes\n\n")
        w(scorecard.notes + "\n")

    return out.getvalue()


def score_deltas(current: Scorecard, previous: Scorecard) -> dict[str, int | None]:
    """Per-dimension score change; None where either scorecard skipped the dimension."""
    now, before = current.by_key(), previous.by_key()
    return {
        d.key: now[d.key].score - before[d.key].score if d.key in now and d.key in before else None
        for d in DIMENSIONS
    }


def fmt_delta(delta: int | None) -> str:
    if delta is None:
        return "—"
    return f"{delta:+d}" if delta else "0"
