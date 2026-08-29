"""Small canonical metrics used by the first release pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from m2riv.engine import PairedCaseResult
from m2riv.gate import MetricDirection


@dataclass(frozen=True, slots=True)
class ExactMatchMetric:
    id: str = "accuracy"
    direction: MetricDirection = MetricDirection.HIGHER_IS_BETTER
    binary: bool = True
    unit: str = "ratio"
    identity_scope: Literal["evidence", "run"] = "evidence"

    def sample(self, pair: PairedCaseResult) -> tuple[float, float]:
        if pair.case.expected is None:
            raise ValueError(
                f"exact-match metric requires expected output for case {pair.case_id!r}"
            )
        return (
            float(pair.baseline.output == pair.case.expected),
            float(pair.candidate.output == pair.case.expected),
        )


@dataclass(frozen=True, slots=True)
class MeanLatencyMetric:
    id: str = "mean_latency_ms"
    direction: MetricDirection = MetricDirection.LOWER_IS_BETTER
    binary: bool = False
    unit: str = "milliseconds"
    identity_scope: Literal["evidence", "run"] = "run"

    def sample(self, pair: PairedCaseResult) -> tuple[float, float] | None:
        if pair.baseline.latency_ms is None or pair.candidate.latency_ms is None:
            return None
        return pair.baseline.latency_ms, pair.candidate.latency_ms
