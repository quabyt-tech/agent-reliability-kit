"""Eval datasets. A dataset is a jsonl file of EvalCase records."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class EvalCase(BaseModel):
    """One row in an eval dataset."""

    id: str
    input: dict[str, Any]
    expected: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class Dataset(BaseModel):
    """A versioned collection of EvalCases."""

    name: str
    version: str = "1"
    cases: list[EvalCase]

    @classmethod
    def from_jsonl(cls, path: str | Path, name: str | None = None) -> Dataset:
        path = Path(path)
        cases: list[EvalCase] = []
        with path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, start=1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                raw = json.loads(line)
                if "id" not in raw:
                    raw["id"] = f"{path.stem}-{i}"
                cases.append(EvalCase(**raw))
        return cls(name=name or path.stem, cases=cases)

    def filter(self, tag: str | None = None) -> Dataset:
        if tag is None:
            return self
        return Dataset(
            name=self.name,
            version=self.version,
            cases=[c for c in self.cases if tag in c.tags],
        )

    def __iter__(self) -> Iterator[EvalCase]:  # type: ignore[override]
        return iter(self.cases)

    def __len__(self) -> int:
        return len(self.cases)
