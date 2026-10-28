"""ExecutionAccuracyScorer: result sets are the ground truth, not SQL strings."""

from __future__ import annotations

from agent_reliability_kit.evals import ExecutionAccuracyScorer


def _score(scorer, got, want):
    return scorer.score(input={}, output={"rows": got}, expected={"rows": want})


def test_identical_rows_pass():
    s = ExecutionAccuracyScorer()
    r = _score(s, [{"region": "emea", "total": 10.0}], [{"region": "emea", "total": 10.0}])
    assert r.passed and r.score == 1.0


def test_row_order_ignored_by_default():
    """SQL without ORDER BY makes no ordering promise, so neither do we."""
    s = ExecutionAccuracyScorer()
    r = _score(s, [{"r": "b"}, {"r": "a"}], [{"r": "a"}, {"r": "b"}])
    assert r.passed


def test_row_order_enforced_when_requested():
    s = ExecutionAccuracyScorer(order_matters=True)
    r = _score(s, [{"r": "b"}, {"r": "a"}], [{"r": "a"}, {"r": "b"}])
    assert not r.passed


def test_column_order_ignored_for_dict_rows():
    s = ExecutionAccuracyScorer()
    r = _score(s, [{"b": 2, "a": 1}], [{"a": 1, "b": 2}])
    assert r.passed


def test_int_and_float_compare_equal():
    s = ExecutionAccuracyScorer()
    assert _score(s, [{"n": 5}], [{"n": 5.0}]).passed


def test_float_noise_tolerated():
    s = ExecutionAccuracyScorer(float_places=4)
    assert _score(s, [{"n": 1.000000002}], [{"n": 1.0}]).passed


def test_float_difference_beyond_tolerance_fails():
    s = ExecutionAccuracyScorer(float_places=4)
    assert not _score(s, [{"n": 1.01}], [{"n": 1.0}]).passed


def test_partial_overlap_scores_between_zero_and_one():
    """A near miss should be diagnosable, but must not pass."""
    s = ExecutionAccuracyScorer()
    r = _score(s, [{"r": "a"}, {"r": "b"}], [{"r": "a"}, {"r": "b"}, {"r": "c"}])
    assert not r.passed
    assert 0.0 < r.score < 1.0
    assert r.metadata["missing"] == [["c"]]


def test_duplicate_rows_are_significant():
    """COUNT-style results differ by row multiplicity; a set compare hides that."""
    s = ExecutionAccuracyScorer()
    assert not _score(s, [{"r": "a"}], [{"r": "a"}, {"r": "a"}]).passed


def test_sequence_rows_supported():
    s = ExecutionAccuracyScorer()
    assert _score(s, [["emea", 10]], [("emea", 10.0)]).passed


def test_missing_expected_is_not_applicable():
    s = ExecutionAccuracyScorer()
    r = s.score(input={}, output={"rows": [{"a": 1}]}, expected={})
    assert r.passed and r.reason == "n/a"


def test_missing_output_rows_fails():
    s = ExecutionAccuracyScorer()
    r = s.score(input={}, output={}, expected={"rows": [{"a": 1}]})
    assert not r.passed


def test_empty_result_sets_match():
    s = ExecutionAccuracyScorer()
    assert _score(s, [], []).passed


def test_empty_vs_nonempty_fails():
    s = ExecutionAccuracyScorer()
    assert not _score(s, [], [{"a": 1}]).passed
