"""Loss analysis. Clusters failed eval runs so you fix themes, not one-offs."""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel

from .harness import EvalResult, RunResult


class FailureCluster(BaseModel):
    """A group of failures sharing the same signature."""

    signature: str
    count: int
    case_ids: list[str]
    sample_reason: str = ""
    theme: str = ""
    """One-line root-cause theme, filled in when a label model is provided."""


def cluster_failures(
    result: EvalResult,
    *,
    label_model: Callable[[str], str] | None = None,
) -> list[FailureCluster]:
    """Group failed runs by failure signature, largest cluster first.

    Signature is deterministic: the error type for errored runs, otherwise the
    sorted set of failing scorer names. Pass `label_model` (prompt -> text) to
    get an LLM-written one-line theme per cluster.
    """
    # ponytail: signature clustering, swap in embedding/LLM clustering if themes get muddy
    groups: dict[str, list[RunResult]] = {}
    for run in result.runs:
        if run.passed:
            continue
        groups.setdefault(_signature(run), []).append(run)

    clusters = [
        FailureCluster(
            signature=sig,
            count=len(runs),
            case_ids=[r.case_id for r in runs],
            sample_reason=_sample_reason(runs[0]),
        )
        for sig, runs in groups.items()
    ]
    clusters.sort(key=lambda c: c.count, reverse=True)

    if label_model is not None:
        for cluster in clusters:
            cluster.theme = _label(cluster, groups[cluster.signature], label_model)
    return clusters


def _signature(run: RunResult) -> str:
    if run.error:
        return f"error:{run.error.split(':', 1)[0]}"
    failing = sorted(s.name for s in run.scores if not s.passed)
    return "+".join(failing) if failing else "no_scores"


def _sample_reason(run: RunResult) -> str:
    if run.error:
        return run.error
    return "; ".join(f"{s.name}: {s.reason}" for s in run.scores if not s.passed)


def _label(
    cluster: FailureCluster, runs: list[RunResult], label_model: Callable[[str], str]
) -> str:
    examples = "\n".join(
        f"- case {r.case_id}: input={r.input} output={r.output} reason={_sample_reason(r)}"
        for r in runs[:5]
    )
    prompt = (
        "These agent eval failures share the signature "
        f"{cluster.signature!r}:\n{examples}\n\n"
        "In one short sentence, name the likely root-cause theme. "
        "Return only the sentence."
    )
    try:
        return label_model(prompt).strip().splitlines()[0][:200]
    except Exception as e:
        return f"(labeling failed: {e})"
