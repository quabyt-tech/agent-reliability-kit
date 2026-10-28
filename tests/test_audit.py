"""Tests for the audit toolkit."""

from __future__ import annotations

from datetime import datetime

from agent_reliability_kit.audit import (
    DIMENSIONS,
    DimensionScore,
    Scorecard,
    overall_score,
)
from agent_reliability_kit.audit.html_report import render_html
from agent_reliability_kit.audit.report import render_markdown, score_deltas


def test_dimensions_weights_sum_to_one():
    assert abs(sum(d.weight for d in DIMENSIONS) - 1.0) < 1e-6


def test_overall_score_perfect():
    scores = [DimensionScore(key=d.key, score=5) for d in DIMENSIONS]
    assert overall_score(scores) == 5.0


def test_overall_score_zero():
    scores = [DimensionScore(key=d.key, score=0) for d in DIMENSIONS]
    assert overall_score(scores) == 0.0


def test_overall_score_mixed():
    scores = [DimensionScore(key=d.key, score=3) for d in DIMENSIONS]
    assert abs(overall_score(scores) - 3.0) < 1e-6


def test_scorecard_verdict_bands():
    scores_3 = [DimensionScore(key=d.key, score=3) for d in DIMENSIONS]
    sc = Scorecard(client="X", agent="Y", scores=scores_3, audited_at=datetime(2026, 1, 1))
    assert "Production-acceptable" in sc.verdict()
    scores_low = [DimensionScore(key=d.key, score=1) for d in DIMENSIONS]
    sc = Scorecard(client="X", agent="Y", scores=scores_low, audited_at=datetime(2026, 1, 1))
    assert sc.verdict() == "Not production-ready"








def test_render_markdown_smoke():
    sc = Scorecard(
        client="Acme Co",
        agent="support-bot",
        audited_at=datetime(2026, 5, 15),
        scores=[
            DimensionScore(key="eval_coverage", score=2, evidence="Some evals in evals/"),
            DimensionScore(
                key="regression_detection",
                score=0,
                evidence="No CI workflow runs evals.",
                recommendations=["Add eval-gate.yml", "Pin model version"],
            ),
        ],
        top_risks=["No CI eval gate — silent regressions on prompt edits."],
    )
    md = render_markdown(scorecard=sc)
    assert "Acme Co" in md
    assert "Eval coverage" in md
    assert "0 / 5" in md
    assert "Add eval-gate.yml" in md


def _month(score: int, day: int) -> Scorecard:
    return Scorecard(
        client="Acme <Co>",
        agent="support-bot",
        audited_at=datetime(2026, 5, day),
        scores=[
            DimensionScore(key="eval_coverage", score=score, evidence="See `evals/golden.jsonl`"),
            DimensionScore(key="guardrails", score=2),
        ],
    )


def test_score_deltas_and_markdown_change_column():
    before, now = _month(2, 1), _month(4, 28)
    deltas = score_deltas(now, before)
    assert deltas["eval_coverage"] == 2 and deltas["guardrails"] == 0
    assert deltas["observability"] is None
    md = render_markdown(scorecard=now, previous=before)
    assert "| Change |" in md and "| +2 |" in md


def test_render_html_escapes_and_shows_change():
    page = render_html(scorecard=_month(4, 28), previous=_month(2, 1))
    assert page.startswith("<!doctype html>")
    assert "Acme &lt;Co&gt;" in page and "<Co>" not in page
    assert "<code>evals/golden.jsonl</code>" in page
    assert 'class="num up">+2<' in page
