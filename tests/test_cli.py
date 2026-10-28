"""End-to-end check of `arkit` against examples/order_bot."""

from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML
from typer.testing import CliRunner

from agent_reliability_kit.cli import app

EXAMPLE = Path(__file__).parent.parent / "examples" / "order_bot"
runner = CliRunner()


def test_golden_passes_and_adversarial_gate_catches_the_leak(monkeypatch):
    monkeypatch.chdir(EXAMPLE)
    ok = runner.invoke(
        app, ["run", "golden.jsonl", "-t", "agent:run", "-s", "scorers:GOLDEN", "--fail-under", "1"]
    )
    assert ok.exit_code == 0, ok.output

    gated = runner.invoke(
        app,
        ["run", "adversarial.jsonl", "-t", "agent:run", "-s", "scorers:ADVERSARIAL",
         "--trap-fail-under", "0.8"],
    )
    assert gated.exit_code == 1
    assert "behavioural_control" in gated.output


def test_template_report_and_diff(tmp_path: Path):
    before = tmp_path / "before.yaml"
    assert runner.invoke(app, ["template", str(before)]).exit_code == 0

    data = YAML(typ="safe", pure=True).load(before.read_text())
    data["scores"][0]["score"] = 3
    after = tmp_path / "after.yaml"
    YAML(typ="safe", pure=True).dump(data, after)

    html = tmp_path / "report.html"
    res = runner.invoke(app, ["report", str(after), "--previous", str(before), "-o", str(html)])
    assert res.exit_code == 0, res.output
    assert "<html" in html.read_text(encoding="utf-8")

    res = runner.invoke(app, ["diff", str(before), str(after)])
    assert res.exit_code == 0 and "+3" in res.output
