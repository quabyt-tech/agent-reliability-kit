"""Eval harness. Runs a target callable over a dataset and aggregates scores."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from .datasets import Dataset, EvalCase
from .scorers import Scorer, ScoreResult

Target = Callable[[dict[str, Any]], Any] | Callable[[dict[str, Any]], Awaitable[Any]]


class RunResult(BaseModel):
    case_id: str
    input: dict[str, Any]
    output: Any
    latency_ms: float
    scores: list[ScoreResult]
    error: str | None = None
    passed: bool

    @property
    def overall_score(self) -> float:
        if not self.scores:
            return 0.0
        return sum(s.score for s in self.scores) / len(self.scores)


class TrapCoverage(BaseModel):
    """Per-trap-class pass rate, mapped to the 6-class taxonomy.

    See docs/trap-taxonomy.md. Cases without a `trap:<class>` tag are ignored.
    """

    trap_class: str
    total: int
    passed: int

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


class EvalResult(BaseModel):
    dataset_name: str
    dataset_version: str
    total: int
    passed: int
    failed: int
    errored: int
    avg_score_by_scorer: dict[str, float] = Field(default_factory=dict)
    trap_coverage: list[TrapCoverage] = Field(default_factory=list)
    runs: list[RunResult]
    started_at: float
    finished_at: float

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def duration_s(self) -> float:
        return self.finished_at - self.started_at

    def trap_class_below(self, threshold: float) -> list[TrapCoverage]:
        return [tc for tc in self.trap_coverage if tc.total and tc.pass_rate < threshold]


@dataclass
class EvalHarness:
    """Run a target over a dataset.

    The target receives `case.input` and returns any value. Scorers see
    `(input, output, expected)`. A case passes only if **every** scorer passes.
    """

    target: Target
    scorers: list[Scorer]
    concurrency: int = 4

    def run(self, dataset: Dataset, *, tag: str | None = None) -> EvalResult:
        return asyncio.run(self.run_async(dataset, tag=tag))

    async def run_async(self, dataset: Dataset, *, tag: str | None = None) -> EvalResult:
        ds = dataset.filter(tag)
        started = time.time()
        sem = asyncio.Semaphore(self.concurrency)

        async def run_one(case: EvalCase) -> RunResult:
            async with sem:
                return await self._run_case(case)

        runs = await asyncio.gather(*(run_one(c) for c in ds.cases))
        finished = time.time()

        avg_by_scorer = _aggregate_scores(runs)
        passed = sum(1 for r in runs if r.passed and not r.error)
        errored = sum(1 for r in runs if r.error)
        failed = len(runs) - passed - errored
        coverage = _aggregate_trap_coverage(ds.cases, runs)

        return EvalResult(
            dataset_name=ds.name,
            dataset_version=ds.version,
            total=len(runs),
            passed=passed,
            failed=failed,
            errored=errored,
            avg_score_by_scorer=avg_by_scorer,
            trap_coverage=coverage,
            runs=runs,
            started_at=started,
            finished_at=finished,
        )

    async def _run_case(self, case: EvalCase) -> RunResult:
        t0 = time.time()
        error: str | None = None
        output: Any = None
        scores: list[ScoreResult] = []
        try:
            output = await _maybe_await(self.target, case.input)
        except Exception as e:  # capture, don't crash the whole run
            error = f"{type(e).__name__}: {e}"
        latency_ms = (time.time() - t0) * 1000

        if error is None:
            for scorer in self.scorers:
                try:
                    scores.append(
                        scorer.score(input=case.input, output=output, expected=case.expected)
                    )
                except Exception as e:
                    scores.append(
                        ScoreResult(
                            name=scorer.name,
                            score=0.0,
                            passed=False,
                            reason=f"scorer crashed: {e}",
                        )
                    )

        passed = bool(scores) and all(s.passed for s in scores) and error is None
        return RunResult(
            case_id=case.id,
            input=case.input,
            output=output,
            latency_ms=latency_ms,
            scores=scores,
            error=error,
            passed=passed,
        )


async def _maybe_await(target: Target, payload: dict[str, Any]) -> Any:
    result = target(payload)
    if inspect.isawaitable(result):
        return await result
    return result


def _aggregate_scores(runs: Iterable[RunResult]) -> dict[str, float]:
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    for r in runs:
        for s in r.scores:
            sums[s.name] = sums.get(s.name, 0.0) + s.score
            counts[s.name] = counts.get(s.name, 0) + 1
    return {k: sums[k] / counts[k] for k in sums}


TRAP_TAG_PREFIX = "trap:"
KNOWN_TRAP_CLASSES = (
    "content_injection",
    "semantic_manipulation",
    "cognitive_state",
    "behavioural_control",
    "systemic",
    "human_in_the_loop",
)


def _aggregate_trap_coverage(
    cases: Iterable[EvalCase], runs: Iterable[RunResult]
) -> list[TrapCoverage]:
    """Pass rate per trap class. See docs/trap-taxonomy.md.

    A case is attributed to a class iff it carries a `trap:<class>` tag.
    Cases without trap tags are ignored (they belong to the golden / edge-case
    coverage, not the trap-surface rubric).
    """
    by_id: dict[str, RunResult] = {r.case_id: r for r in runs}
    totals: dict[str, int] = {}
    passes: dict[str, int] = {}
    for case in cases:
        trap_classes = [
            t[len(TRAP_TAG_PREFIX) :] for t in case.tags if t.startswith(TRAP_TAG_PREFIX)
        ]
        if not trap_classes:
            continue
        run = by_id.get(case.id)
        if run is None:
            continue
        for cls in trap_classes:
            totals[cls] = totals.get(cls, 0) + 1
            if run.passed:
                passes[cls] = passes.get(cls, 0) + 1
    # Order: known classes first (stable), then any unknown ones for surfacing typos.
    ordered: list[str] = [c for c in KNOWN_TRAP_CLASSES if c in totals]
    ordered += sorted(c for c in totals if c not in KNOWN_TRAP_CLASSES)
    return [
        TrapCoverage(trap_class=cls, total=totals[cls], passed=passes.get(cls, 0))
        for cls in ordered
    ]
