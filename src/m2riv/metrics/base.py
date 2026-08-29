"""Stable metric boundary independent of adapters and execution fabrics."""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from m2riv.engine import PairedCaseResult
from m2riv.gate import MetricDirection


@runtime_checkable
class PairedMetric(Protocol):
    """Extract one candidate/baseline numeric pair from paired evidence."""

    @property
    def id(self) -> str: ...

    @property
    def direction(self) -> MetricDirection: ...

    @property
    def binary(self) -> bool: ...

    @property
    def unit(self) -> str: ...

    @property
    def identity_scope(self) -> Literal["evidence", "run"]: ...

    def sample(self, pair: PairedCaseResult) -> tuple[float, float] | None:
        """Return baseline/candidate values, or None when evidence is unavailable."""
        ...
