"""The 8-dimension reliability scorecard. Mirrors docs/reliability-scorecard.md.

Engineers score each dimension 0..5 during the audit; this module renders the
result deterministically.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


@dataclass(frozen=True)
class Dimension:
    key: str
    name: str
    weight: float
    """Fraction of the overall score, sums to 1.0 across DIMENSIONS."""
    description: str


DIMENSIONS: tuple[Dimension, ...] = (
    Dimension(
        key="eval_coverage",
        name="Eval coverage",
        weight=0.20,
        description="Golden + adversarial + per-step evals; production sampling feeds back.",
    ),
    Dimension(
        key="regression_detection",
        name="Regression detection",
        weight=0.15,
        description="CI gates on prompt/tool/model changes; trended pass rates.",
    ),
    Dimension(
        key="guardrails",
        name="Guardrails",
        weight=0.15,
        description="Input + output + tool-use validation; HITL on high-stakes.",
    ),
    Dimension(
        key="observability",
        name="Observability",
        weight=0.15,
        description="OTel gen_ai.* spans, retention, cross-system correlation.",
    ),
    Dimension(
        key="cost_controls",
        name="Cost controls",
        weight=0.10,
        description="Per-request token/dollar accounting, budgets, model routing.",
    ),
    Dimension(
        key="failure_mode_mapping",
        name="Failure-mode mapping",
        weight=0.10,
        description="Documented failure modes, each with detection + mitigation.",
    ),
    Dimension(
        key="security",
        name="Security & data handling",
        weight=0.10,
        description="PII handling, least-priv IAM, audit log, prompt-injection defense.",
    ),
    Dimension(
        key="deployment",
        name="Deployment & operations",
        weight=0.05,
        description="IaC, feature flags, on-call runbook, rollback.",
    ),
)


# Sanity: weights sum to 1.0
assert abs(sum(d.weight for d in DIMENSIONS) - 1.0) < 1e-6


def get_dimension(key: str) -> Dimension:
    for d in DIMENSIONS:
        if d.key == key:
            return d
    raise KeyError(f"unknown dimension: {key}")


class DimensionScore(BaseModel):
    key: str
    score: int = Field(ge=0, le=5)
    evidence: str = ""
    """One or two sentences with file paths, trace IDs, or screenshots."""
    recommendations: list[str] = Field(default_factory=list)

    @field_validator("key")
    @classmethod
    def _known_key(cls, v: str) -> str:
        get_dimension(v)
        return v


class Scorecard(BaseModel):
    client: str
    agent: str
    auditor: str = ""
    audited_at: datetime = Field(default_factory=datetime.utcnow)
    scores: list[DimensionScore]
    top_risks: list[str] = Field(default_factory=list)
    notes: str = ""

    def overall(self) -> float:
        return overall_score(self.scores)

    def verdict(self) -> str:
        return verdict_for(self.overall())

    def by_key(self) -> dict[str, DimensionScore]:
        return {s.key: s for s in self.scores}


def overall_score(scores: Iterable[DimensionScore]) -> float:
    by_key = {s.key: s for s in scores}
    total = 0.0
    for d in DIMENSIONS:
        s = by_key.get(d.key)
        if s is None:
            # Missing dimension scored as 0 — explicit and harsh on purpose.
            continue
        total += s.score * d.weight
    return round(total, 2)


def verdict_for(overall: float) -> str:
    if overall < 2.0:
        return "Not production-ready"
    if overall < 3.0:
        return "Pilot-quality only"
    if overall < 4.0:
        return "Production-acceptable (non-critical)"
    if overall <= 4.5:
        return "Mature"
    return "Industry leading"


class TraceFinding(BaseModel):
    """One finding from trace analysis, shown in the report."""

    name: str
    severity: str  # P0 | P1 | P2
    count: int
    description: str
    sample_trace_ids: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
