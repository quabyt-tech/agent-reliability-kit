"""CitationGroundingScorer: claims must trace to sources that were retrieved."""

from __future__ import annotations

from agent_reliability_kit.evals import CitationGroundingScorer

SOURCES = [{"id": "s1", "domain": "docs.internal"}, {"id": "s2", "domain": "wikipedia.org"}]


def _score(scorer, claims, sources=SOURCES, expected=None):
    return scorer.score(input={}, output={"claims": claims, "sources": sources}, expected=expected)


def test_all_claims_grounded_passes():
    s = CitationGroundingScorer()
    r = _score(s, [{"text": "a", "sources": ["s1"]}, {"text": "b", "sources": ["s2"]}])
    assert r.passed and r.score == 1.0


def test_uncited_claim_fails():
    """A statement with no source is the agent's prior knowledge presented as
    research."""
    s = CitationGroundingScorer()
    r = _score(s, [{"text": "a", "sources": ["s1"]}, {"text": "b", "sources": []}])
    assert not r.passed
    assert r.score == 0.5
    assert r.metadata["uncited"] == ["b"]


def test_fabricated_citation_fails_even_at_full_ratio():
    """A claim citing both a real and an invented source still counts as
    grounded by ratio, but a fabricated id must fail the case outright: it is
    the failure that survives human review."""
    s = CitationGroundingScorer()
    r = _score(s, [{"text": "a", "sources": ["s1", "s99"]}])
    assert r.score == 1.0
    assert not r.passed
    assert r.metadata["fabricated"] == ["s99"]


def test_claim_citing_only_fabricated_source_is_ungrounded():
    s = CitationGroundingScorer()
    r = _score(s, [{"text": "a", "sources": ["ghost"]}])
    assert r.score == 0.0
    assert not r.passed


def test_partial_score_is_diagnosable():
    s = CitationGroundingScorer()
    claims = [{"text": f"c{i}", "sources": ["s1"]} for i in range(4)]
    claims.append({"text": "bad", "sources": []})
    r = _score(s, claims)
    assert r.score == 0.8
    assert not r.passed


def test_threshold_can_be_relaxed():
    s = CitationGroundingScorer(threshold=0.75)
    claims = [{"text": f"c{i}", "sources": ["s1"]} for i in range(3)]
    claims.append({"text": "bad", "sources": []})
    assert _score(s, claims).passed


def test_allowed_sources_from_expected_overrides_output():
    """Pinning the valid set in the case stops an agent from grading itself by
    reporting whatever sources it wishes it had retrieved."""
    s = CitationGroundingScorer()
    r = _score(
        s,
        [{"text": "a", "sources": ["s1"]}],
        sources=[{"id": "s1"}],
        expected={"allowed_sources": ["only-this"]},
    )
    assert not r.passed
    assert r.metadata["fabricated"] == ["s1"]


def test_string_sources_supported():
    s = CitationGroundingScorer()
    assert _score(s, [{"text": "a", "sources": "s1"}], sources=["s1"]).passed


def test_citations_key_accepted_as_alias():
    s = CitationGroundingScorer()
    assert _score(s, [{"text": "a", "citations": ["s1"]}]).passed


def test_plain_string_claim_is_ungrounded():
    s = CitationGroundingScorer()
    assert not _score(s, ["an uncited assertion"]).passed


def test_no_claims_asserted_is_trivially_grounded():
    s = CitationGroundingScorer()
    r = _score(s, [])
    assert r.passed and r.reason == "no claims asserted"


def test_missing_claims_field_fails():
    s = CitationGroundingScorer()
    r = s.score(input={}, output={"sources": SOURCES}, expected=None)
    assert not r.passed
