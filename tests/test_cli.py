"""End-to-end check of `arkit` against examples/support_agent."""

from __future__ import annotations

import sys
from pathlib import Path

from ruamel.yaml import YAML
from typer.testing import CliRunner

from agent_reliability_kit.cli import app

EXAMPLE = Path(__file__).parent.parent / "examples" / "support_agent"
runner = CliRunner()


def test_version_flag_and_command_agree():
    flag, cmd = runner.invoke(app, ["--version"]), runner.invoke(app, ["version"])
    assert flag.exit_code == cmd.exit_code == 0
    assert flag.output == cmd.output != ""


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
    # 36 of 40 pass overall, which would clear a single 80% gate; the class gate still fails.
    assert gated.exit_code == 1
    assert "90.00%" in gated.output
    assert "behavioural_control pass rate 0.00% below 80.00% (0/4)" in gated.output


def test_common_mistakes_get_a_clear_error(monkeypatch, tmp_path: Path):
    dataset = str(EXAMPLE / "golden.jsonl")
    # Not the example folder, and forget any earlier import of it, so agent.py can't be found.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "path", [p for p in sys.path if Path(p).resolve() != EXAMPLE.resolve()])
    for mod in ("agent", "scorers", "store"):
        monkeypatch.delitem(sys.modules, mod, raising=False)
    wrong_dir = runner.invoke(app, ["run", dataset, "-t", "agent:run", "-s", "scorers:GOLDEN"])
    assert wrong_dir.exit_code == 2
    assert "Run arkit from the folder that holds agent.py" in wrong_dir.output

    monkeypatch.setenv("AR_TARGET_HEADERS", "not json")
    bad_headers = runner.invoke(
        app, ["run", dataset, "-t", "http://localhost:1/agent", "-s", "scorers:GOLDEN"]
    )
    assert bad_headers.exit_code == 2
    assert "AR_TARGET_HEADERS must be a JSON object" in bad_headers.output


def test_run_fails_when_every_case_errors(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(EXAMPLE)
    one_case = tmp_path / "one.jsonl"
    one_case.write_text((EXAMPLE / "golden.jsonl").read_text().splitlines()[0] + "\n")
    # Nothing listens on port 1, so the request fails to connect.
    res = runner.invoke(
        app, ["run", str(one_case), "-t", "http://localhost:1/agent", "-s", "scorers:GOLDEN"]
    )
    assert res.exit_code == 1
    assert "Every case errored" in res.output


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
