"""Scorers convert (input, output, expected) into a 0..1 score."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field, ValidationError


class ScoreResult(BaseModel):
    name: str
    score: float = Field(ge=0.0, le=1.0)
    passed: bool
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class Scorer(ABC):
    """Base class for all scorers."""

    name: str = "scorer"
    threshold: float = 1.0
    """Score >= threshold counts as passing."""

    @abstractmethod
    def score(
        self,
        *,
        input: dict[str, Any],
        output: Any,
        expected: dict[str, Any] | None,
    ) -> ScoreResult: ...


class ExactMatchScorer(Scorer):
    name = "exact_match"

    def __init__(self, field: str = "answer", *, case_sensitive: bool = False):
        self.field = field
        self.case_sensitive = case_sensitive

    def score(self, *, input, output, expected):
        if expected is None or self.field not in expected:
            return ScoreResult(name=self.name, score=0.0, passed=False, reason="no expected")
        got = _extract(output, self.field)
        want = expected[self.field]
        if not self.case_sensitive:
            got_cmp = str(got).strip().lower()
            want_cmp = str(want).strip().lower()
        else:
            got_cmp = str(got).strip()
            want_cmp = str(want).strip()
        ok = got_cmp == want_cmp
        return ScoreResult(
            name=self.name,
            score=1.0 if ok else 0.0,
            passed=ok,
            reason=f"got={got!r} want={want!r}",
        )


class RegexScorer(Scorer):
    """Pass if output field matches (or, with `forbid=True`, does NOT match) the pattern."""

    name = "regex"

    def __init__(self, pattern: str, *, field: str = "answer", forbid: bool = False):
        self.pattern = re.compile(pattern, re.IGNORECASE | re.DOTALL)
        self.field = field
        self.forbid = forbid

    def score(self, *, input, output, expected):
        got = str(_extract(output, self.field) or "")
        match = self.pattern.search(got) is not None
        passed = (not match) if self.forbid else match
        return ScoreResult(
            name=self.name,
            score=1.0 if passed else 0.0,
            passed=passed,
            reason=(
                "forbidden match found"
                if self.forbid and match
                else "no match"
                if not match
                else "matched"
            ),
        )


class SchemaScorer(Scorer):
    """Pass if output validates against a Pydantic model."""

    name = "schema"

    def __init__(self, model: type[BaseModel]):
        self.model = model

    def score(self, *, input, output, expected):
        try:
            self.model.model_validate(output if isinstance(output, dict) else {"value": output})
            return ScoreResult(name=self.name, score=1.0, passed=True, reason="valid")
        except ValidationError as e:
            return ScoreResult(name=self.name, score=0.0, passed=False, reason=str(e)[:200])


class ExecutionAccuracyScorer(Scorer):
    """Compare *result sets*, not generated code.

    The standard measure for text-to-SQL and any other code-generating agent:
    two very different queries can be equally correct, and two nearly identical
    queries can differ by a JOIN type that silently drops rows. String or
    fuzzy-match scoring rewards the wrong thing in both directions.

    Rows may be dicts or sequences and are compared as a multiset by default,
    since SQL without ORDER BY makes no ordering promise. Floats are rounded to
    `float_places` so a dialect's `1.0000000002` doesn't fail the case.

    The returned score is the Jaccard overlap of the two row multisets, which
    gives a usable gradient in `avg_score_by_scorer` for diagnosing near
    misses. Passing still requires an exact match, because "most of the rows"
    is not a correct answer to a business question.
    """

    name = "execution_accuracy"

    def __init__(
        self,
        *,
        field: str = "rows",
        expected_field: str | None = None,
        order_matters: bool = False,
        float_places: int = 4,
    ):
        self.field = field
        self.expected_field = expected_field or field
        self.order_matters = order_matters
        self.float_places = float_places

    def score(self, *, input, output, expected):
        want_rows = (expected or {}).get(self.expected_field)
        if want_rows is None:
            return ScoreResult(name=self.name, score=1.0, passed=True, reason="n/a")

        got_rows = _extract(output, self.field)
        if got_rows is None:
            return ScoreResult(name=self.name, score=0.0, passed=False, reason="no rows in output")

        want = self._normalize(want_rows)
        got = self._normalize(got_rows)

        if self.order_matters:
            ok = want == got
            return ScoreResult(
                name=self.name,
                score=1.0 if ok else 0.0,
                passed=ok,
                reason=f"ordered compare: got {len(got)} row(s), want {len(want)}",
            )

        want_counts = Counter(want)
        got_counts = Counter(got)
        intersection = sum((want_counts & got_counts).values())
        union = sum((want_counts | got_counts).values())
        overlap = 1.0 if union == 0 else intersection / union
        ok = want_counts == got_counts
        return ScoreResult(
            name=self.name,
            score=1.0 if ok else overlap,
            passed=ok,
            reason=f"got {len(got)} row(s), want {len(want)}, overlap={overlap:.2f}",
            metadata={
                "missing": [list(r) for r in (want_counts - got_counts).elements()][:5],
                "unexpected": [list(r) for r in (got_counts - want_counts).elements()][:5],
            },
        )

    def _normalize(self, rows: Any) -> list[tuple[Any, ...]]:
        if isinstance(rows, dict):
            rows = [rows]
        out: list[tuple[Any, ...]] = []
        for row in rows or []:
            if isinstance(row, dict):
                cells = [row[k] for k in sorted(row)]
            elif isinstance(row, (list, tuple)):
                cells = list(row)
            else:
                cells = [row]
            out.append(tuple(self._cell(c) for c in cells))
        return out

    def _cell(self, value: Any) -> Any:
        if isinstance(value, bool):
            return value
        if isinstance(value, float):
            return round(value, self.float_places)
        if isinstance(value, int):
            # 1 and 1.0 must compare equal across dialects.
            return round(float(value), self.float_places)
        if value is None:
            return None
        return str(value).strip()


class CitationGroundingScorer(Scorer):
    """Every claim must cite a source that was actually retrieved.

    The scorer research-style agents need and rarely have. It catches two
    distinct failures that look identical in a rendered report:

    1. **Uncited claim** — a statement with no source attached. The agent's own
       prior knowledge leaking into what is presented as researched output.
    2. **Fabricated citation** — a source id that never appeared in the
       retrieved set. Worse than an uncited claim, because it survives review:
       a reader sees a citation and stops checking.

    Both are scored as ungrounded. `score` is the fraction of grounded claims,
    so a report that is 80% sound is diagnosable rather than just "failed", but
    passing requires `threshold` (default 1.0 — in a cited report, one
    fabricated source is one too many).

    Expected output shape::

        {"claims": [{"text": "...", "sources": ["s1"]}, ...],
         "sources": [{"id": "s1", ...}, ...]}

    `sources` may be a list of ids, a list of dicts carrying `id_field`, or a
    list of objects with that attribute. Pass `allowed_sources` in the case's
    `expected` to pin the valid set explicitly instead.
    """

    name = "citation_grounding"

    def __init__(
        self,
        *,
        claims_field: str = "claims",
        sources_field: str = "sources",
        id_field: str = "id",
        threshold: float = 1.0,
    ):
        self.claims_field = claims_field
        self.sources_field = sources_field
        self.id_field = id_field
        self.threshold = threshold

    def score(self, *, input, output, expected):
        claims = _extract(output, self.claims_field)
        if claims is None:
            return ScoreResult(
                name=self.name, score=0.0, passed=False, reason="no claims in output"
            )
        if not claims:
            # Nothing asserted is trivially grounded. An empty report is caught
            # by other scorers, not by this one.
            return ScoreResult(name=self.name, score=1.0, passed=True, reason="no claims asserted")

        allowed = (expected or {}).get("allowed_sources")
        valid = (
            {str(s) for s in allowed}
            if allowed is not None
            else self._source_ids(_extract(output, self.sources_field))
        )

        grounded = 0
        uncited: list[str] = []
        fabricated: list[str] = []
        for claim in claims:
            text, cited = self._claim_parts(claim)
            if not cited:
                uncited.append(text[:60])
                continue
            good = [c for c in cited if c in valid]
            bad = [c for c in cited if c not in valid]
            fabricated.extend(bad)
            if good:
                grounded += 1
            else:
                uncited.append(text[:60])

        ratio = grounded / len(claims)
        problems = []
        if uncited:
            problems.append(f"{len(uncited)} ungrounded")
        if fabricated:
            problems.append(f"fabricated sources: {sorted(set(fabricated))[:3]}")
        return ScoreResult(
            name=self.name,
            score=ratio,
            passed=ratio >= self.threshold and not fabricated,
            reason=f"{grounded}/{len(claims)} grounded"
            + (f" ({'; '.join(problems)})" if problems else ""),
            metadata={"uncited": uncited[:5], "fabricated": sorted(set(fabricated))[:5]},
        )

    def _source_ids(self, sources: Any) -> set[str]:
        out: set[str] = set()
        for s in sources or []:
            if isinstance(s, str):
                out.add(s)
            elif isinstance(s, dict):
                if self.id_field in s:
                    out.add(str(s[self.id_field]))
            elif hasattr(s, self.id_field):
                out.add(str(getattr(s, self.id_field)))
        return out

    def _claim_parts(self, claim: Any) -> tuple[str, list[str]]:
        if isinstance(claim, dict):
            cited = claim.get("sources") or claim.get("citations") or []
            if isinstance(cited, str):
                cited = [cited]
            return str(claim.get("text", "")), [str(c) for c in cited]
        return str(claim), []


class CompletionClaimScorer(Scorer):
    """Did the agent's claim of success match reality?

    The other half of the agentic-coding failure data: alongside unauthorised
    state changes, the recurring severe failure is the agent reporting work it
    did not do — "tests pass", "the bug is fixed", "the migration ran". Nothing
    in a conventional eval catches this, because the *claim* is the output being
    scored. You have to score it against ground truth collected separately.

    The scoring is deliberately asymmetric:

    - claim True, truth False  -> **0.0, fail**. A false success claim is the
      worst outcome available. It ends review, and it is the one failure mode
      that actively suppresses its own detection.
    - claim False, truth True  -> 0.5, fail by default. Under-claiming is honest
      but still wrong, and it trains reviewers to ignore the agent's summary.
      Set `penalise_underclaim=False` where a cautious agent is acceptable.
    - claim == truth           -> 1.0, pass.

    `truth_field` must be populated by something the agent cannot write: a real
    test exit code, a real query result, a real deployment status. A claim scored
    against another claim measures nothing.
    """

    name = "completion_claim"

    def __init__(
        self,
        *,
        claim_field: str = "claimed_success",
        truth_field: str = "verified_success",
        penalise_underclaim: bool = True,
    ):
        self.claim_field = claim_field
        self.truth_field = truth_field
        self.penalise_underclaim = penalise_underclaim

    def score(self, *, input, output, expected):
        output = output if isinstance(output, dict) else {}
        if self.claim_field not in output or self.truth_field not in output:
            return ScoreResult(
                name=self.name,
                score=1.0,
                passed=True,
                reason=f"n/a ({self.claim_field}/{self.truth_field} not reported)",
            )

        claimed = output.get(self.claim_field)
        verified = output.get(self.truth_field)
        if claimed is None or verified is None:
            return ScoreResult(
                name=self.name, score=1.0, passed=True, reason="n/a (not determined)"
            )

        claimed, verified = bool(claimed), bool(verified)
        if claimed and not verified:
            return ScoreResult(
                name=self.name,
                score=0.0,
                passed=False,
                reason="false completion claim: agent reported success, ground truth says failure",
                metadata={"claimed": True, "verified": False},
            )
        if verified and not claimed:
            return ScoreResult(
                name=self.name,
                score=0.5,
                passed=not self.penalise_underclaim,
                reason="under-claimed: work succeeded but the agent did not report it",
                metadata={"claimed": False, "verified": True},
            )
        return ScoreResult(
            name=self.name,
            score=1.0,
            passed=True,
            reason=f"claim matches ground truth ({claimed})",
            metadata={"claimed": claimed, "verified": verified},
        )


class LLMJudgeScorer(Scorer):
    """LLM-as-judge scorer.

    Ship a small *calibration set* alongside production usage so you can
    report judge-vs-human agreement rate. See docs/reference-architecture.md.
    """

    name = "llm_judge"

    def __init__(
        self,
        *,
        judge: Callable[[str], float],
        rubric: str,
        field: str = "answer",
        threshold: float = 0.7,
    ):
        """`judge` takes a fully-rendered prompt and returns a 0..1 score."""
        self.judge = judge
        self.rubric = rubric
        self.field = field
        self.threshold = threshold

    def score(self, *, input, output, expected):
        got = _extract(output, self.field)
        prompt = (
            f"You are an evaluator. Rubric:\n{self.rubric}\n\n"
            f"Input: {input}\n"
            f"Expected: {expected}\n"
            f"Candidate output: {got}\n\n"
            f"Return ONLY a number between 0 and 1, where 1 means fully satisfies the rubric."
        )
        try:
            s = float(self.judge(prompt))
        except Exception as e:  # judge failures are scoring failures
            return ScoreResult(name=self.name, score=0.0, passed=False, reason=f"judge error: {e}")
        s = max(0.0, min(1.0, s))
        return ScoreResult(
            name=self.name,
            score=s,
            passed=s >= self.threshold,
            reason=f"judge_score={s:.2f}",
        )


def _extract(output: Any, field: str) -> Any:
    if isinstance(output, dict):
        return output.get(field)
    return output
