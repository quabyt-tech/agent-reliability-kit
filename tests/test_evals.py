"""Unit tests for the eval harness primitives."""

from __future__ import annotations

from pathlib import Path

from agent_reliability_kit.evals import Dataset, EvalHarness, ExactMatchScorer, RegexScorer


def test_dataset_load(tmp_path: Path):
    path = tmp_path / "ds.jsonl"
    path.write_text(
        '{"id": "1", "input": {"q": "a"}, "expected": {"answer": "A"}}\n'
        '{"id": "2", "input": {"q": "b"}, "expected": {"answer": "B"}}\n'
    )
    ds = Dataset.from_jsonl(path)
    assert len(ds) == 2
    assert ds.cases[0].id == "1"


def test_harness_exact_match_pass():
    def target(payload):
        return {"answer": payload["q"].upper()}

    ds = Dataset(
        name="t",
        cases=[
            {"id": "1", "input": {"q": "a"}, "expected": {"answer": "A"}},  # type: ignore[list-item]
        ],
    )
    harness = EvalHarness(target=target, scorers=[ExactMatchScorer(field="answer")])
    result = harness.run(ds)
    assert result.pass_rate == 1.0


def test_harness_regex_forbid():
    def target(payload):
        return {"answer": "no secrets here"}

    ds = Dataset(
        name="t",
        cases=[{"id": "1", "input": {"q": "x"}, "expected": None}],  # type: ignore[list-item]
    )
    harness = EvalHarness(
        target=target,
        scorers=[RegexScorer(pattern=r"password", field="answer", forbid=True)],
    )
    result = harness.run(ds)
    assert result.passed == 1


def test_harness_records_error():
    def target(payload):
        raise RuntimeError("boom")

    ds = Dataset(
        name="t",
        cases=[{"id": "1", "input": {"q": "x"}, "expected": None}],  # type: ignore[list-item]
    )
    harness = EvalHarness(target=target, scorers=[ExactMatchScorer()])
    result = harness.run(ds)
    assert result.errored == 1
    assert result.passed == 0


def test_trap_coverage_aggregates_per_class():
    def target(payload):
        return {"answer": payload["q"]}

    ds = Dataset(
        name="t",
        cases=[
            {  # type: ignore[list-item]
                "id": "ci1",
                "input": {"q": "ok"},
                "expected": {"answer": "ok"},
                "tags": ["trap:content_injection", "subtrap:web_standard_obfuscation"],
            },
            {  # type: ignore[list-item]
                "id": "ci2",
                "input": {"q": "ok"},
                "expected": {"answer": "WRONG"},
                "tags": ["trap:content_injection", "subtrap:syntactic_masking"],
            },
            {  # type: ignore[list-item]
                "id": "bc1",
                "input": {"q": "ok"},
                "expected": {"answer": "ok"},
                "tags": ["trap:behavioural_control", "subtrap:embedded_jailbreak"],
            },
            {  # type: ignore[list-item]
                "id": "untagged",
                "input": {"q": "ok"},
                "expected": {"answer": "ok"},
                "tags": ["edge_case"],
            },
        ],
    )
    harness = EvalHarness(target=target, scorers=[ExactMatchScorer(field="answer")])
    result = harness.run(ds)

    by_class = {tc.trap_class: tc for tc in result.trap_coverage}
    assert set(by_class) == {"content_injection", "behavioural_control"}
    assert by_class["content_injection"].total == 2
    assert by_class["content_injection"].passed == 1
    assert by_class["behavioural_control"].pass_rate == 1.0

    failing = result.trap_class_below(0.8)
    assert [tc.trap_class for tc in failing] == ["content_injection"]
