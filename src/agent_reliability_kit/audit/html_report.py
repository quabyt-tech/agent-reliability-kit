"""The audit report as one self-contained HTML page for the client.

Same content as `render_markdown`, laid out for a CTO rather than an engineer: no
external assets, light/dark aware, and print-ready (browser "Save as PDF").
"""

from __future__ import annotations

import html
import re
from string import Template

from .report import fmt_delta, score_deltas
from .scorecard import DIMENSIONS, Scorecard, TraceFinding


def render_html(
    *,
    scorecard: Scorecard,
    repo_signals: dict | None = None,
    trace_findings: list[TraceFinding] | None = None,
    previous: Scorecard | None = None,
) -> str:
    e = html.escape
    by_key = scorecard.by_key()
    deltas = score_deltas(scorecard, previous) if previous else {}
    overall = scorecard.overall()

    rows = []
    for d in DIMENSIONS:
        s = by_key.get(d.key)
        score = s.score if s else 0
        change = ""
        if previous:
            delta = deltas.get(d.key)
            cls = "up" if delta and delta > 0 else "down" if delta and delta < 0 else ""
            change = f'<td class="num {cls}">{fmt_delta(delta)}</td>'
        rows.append(
            f"<tr><td><strong>{e(d.name)}</strong><div class=muted>{e(d.description)}</div></td>"
            f"<td class=num>{f'{score}/5' if s else '&mdash;'}</td>{change}"
            f'<td class=barcell><div class=bar><span class="lvl{score}" '
            f'style="width:{score * 20}%"></span></div></td>'
            f"<td class=num>{int(d.weight * 100)}%</td></tr>"
        )

    sections = []
    if scorecard.top_risks:
        items = "".join(f"<li>{_inline(r)}</li>" for r in scorecard.top_risks)
        sections.append(f"<h2>Top risks</h2><ol>{items}</ol>")

    cards = []
    for d in DIMENSIONS:
        s = by_key.get(d.key)
        if s is None:
            continue
        recs = "".join(f"<li>{_inline(r)}</li>" for r in s.recommendations)
        cards.append(
            f"<article><h3>{e(d.name)} <span class=pill>{s.score}/5</span></h3>"
            + (f"<p>{_inline(s.evidence)}</p>" if s.evidence else "")
            + (f"<h4>Recommendations</h4><ul>{recs}</ul>" if recs else "")
            + "</article>"
        )
    sections.append("<h2>Findings by dimension</h2>" + "".join(cards))

    if trace_findings:
        trs = "".join(
            f"<tr><td><span class=pill>{e(f.severity)}</span></td><td><strong>{e(f.name)}"
            f"</strong><div class=muted>{e(f.description)}</div></td>"
            f"<td class=num>{f.count}</td></tr>"
            for f in trace_findings
        )
        sections.append(
            "<h2>Trace findings</h2><table><tr><th>Severity</th><th>Finding</th>"
            f"<th class=num>Count</th></tr>{trs}</table>"
        )

    if repo_signals and repo_signals.get("matched"):
        trs = "".join(
            f"<tr><td>{e(name)}</td><td class=num>{len(files)} file(s)</td></tr>"
            for name, files in sorted(repo_signals["matched"].items())
        )
        sections.append(
            "<h2>Repo signals</h2><p class=muted>Static patterns found in the code. "
            f"Pointers for the reviewer, not a verdict.</p><table>{trs}</table>"
        )

    if scorecard.notes:
        sections.append(f"<h2>Notes</h2><p>{_inline(scorecard.notes)}</p>")

    change_line = ""
    if previous:
        change_line = (
            f"<div class=muted>{overall - previous.overall():+.2f} since "
            f"{previous.audited_at.date().isoformat()} (was {previous.overall():.2f})</div>"
        )

    return _PAGE.substitute(
        title=e(f"Reliability report: {scorecard.client}"),
        client=e(scorecard.client),
        agent=e(scorecard.agent),
        auditor=e(scorecard.auditor),
        date=scorecard.audited_at.date().isoformat(),
        overall=f"{overall:.2f}",
        verdict=e(scorecard.verdict()),
        change_line=change_line,
        change_head="<th class=num>Change</th>" if previous else "",
        rows="".join(rows),
        sections="".join(sections),
    )


def _inline(text: str) -> str:
    """Escape, then render `code` spans and paragraph breaks."""
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", html.escape(text.strip()))
    return out.replace("\n\n", "</p><p>").replace("\n", " ")


_PAGE = Template("""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>$title</title>
<style>
:root { --bg:#fbfaf7; --fg:#1d1c1a; --muted:#6b6862; --line:#e4e1da; --card:#fff;
  --accent:#2f5d50; --up:#2f7d4f; --down:#b3412e; --warn:#c98a1b; }
@media (prefers-color-scheme: dark) { :root { --bg:#161614; --fg:#ecebe6; --muted:#a19e96;
  --line:#2e2d2a; --card:#1f1e1b; --accent:#7fb8a4; --up:#6cc28f; --down:#e2806c; --warn:#e0b05a; } }
* { box-sizing:border-box }
body { margin:0; background:var(--bg); color:var(--fg);
  font:15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width:960px; margin:0 auto; padding:40px 16px 64px; }
header { display:flex; flex-wrap:wrap; gap:24px; justify-content:space-between; align-items:end;
  border-bottom:2px solid var(--fg); padding-bottom:20px; margin-bottom:28px; }
h1 { font-size:28px; margin:0 0 6px; } h2 { margin:36px 0 12px; font-size:20px; }
h3 { margin:0 0 6px; font-size:16px; }
h4 { margin:12px 0 4px; font-size:12px; text-transform:uppercase; letter-spacing:.04em;
  color:var(--muted); }
.muted { color:var(--muted); font-size:13px; }
.score { text-align:right; } .score b { font-size:44px; line-height:1; }
table { width:100%; border-collapse:collapse; }
th, td { text-align:left; padding:10px 8px; border-bottom:1px solid var(--line); vertical-align:top; }
th { font-size:12px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); }
.num { text-align:right; white-space:nowrap; font-variant-numeric:tabular-nums; }
.up { color:var(--up); font-weight:600; } .down { color:var(--down); font-weight:600; }
.barcell { width:30%; }
.bar { position:relative; height:8px; background:var(--line); border-radius:4px; margin-top:7px; }
.bar span { display:block; height:100%; border-radius:4px; background:var(--accent); }
.bar .lvl0, .bar .lvl1 { background:var(--down); }
.bar .lvl2 { background:var(--warn); }
/* tick at 3/5, the production bar */
.bar::after { content:""; position:absolute; left:60%; top:-4px; width:2px; height:16px;
  background:var(--fg); opacity:.45; }
article { background:var(--card); border:1px solid var(--line); border-radius:8px;
  padding:16px 18px; margin:12px 0; }
article p { margin:6px 0; }
.pill { display:inline-block; font-size:12px; padding:1px 8px; border-radius:99px;
  border:1px solid var(--line); color:var(--muted); font-weight:500; }
code { font-size:.9em; background:var(--line); padding:1px 4px; border-radius:3px;
  overflow-wrap:anywhere; }
@media (max-width:640px) { .barcell { display:none; } }
@media print { :root { --bg:#fff; --card:#fff; } article { break-inside:avoid; } }
</style></head>
<body><main>
<header>
  <div><div class=muted>Agent reliability report</div><h1>$client</h1>
    <div class=muted>$agent &middot; $auditor &middot; $date</div></div>
  <div class=score><b>$overall</b> / 5<div><strong>$verdict</strong></div>$change_line</div>
</header>
<table><tr><th>Dimension</th><th class=num>Score</th>$change_head<th class=barcell></th>
<th class=num>Weight</th></tr>
$rows</table>
$sections
<p class=muted style="margin-top:48px">Scored against the <a href="https://github.com/quabyt-tech/agent-reliability-kit">Agent Reliability Scorecard</a>:
8 dimensions, each 0&ndash;5. A 3 on every dimension is the production bar.</p>
</main></body></html>
""")
