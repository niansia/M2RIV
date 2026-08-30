"""Capability-negotiated boundary between model sources and the Merriv kernel."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Protocol, runtime_checkable

from merriv.core.models import EvalCase, ModelSnapshot, Observation, RuntimeProfile


class AdapterCapability(StrEnum):
    BATCH = "batch"
    STREAMING = "streaming"
    LOGPROBS = "logprobs"
    ACTIVATIONS = "activations"
    TOOL_CALLS = "tool_calls"
    VISION = "vision"
    HARDWARE_METRICS = "hardware_metrics"


@runtime_checkable
class ModelAdapter(Protocol):
    """Minimal source contract; scheduling and statistics remain outside adapters."""

    def describe(self) -> ModelSnapshot:
        """Resolve the execution-relevant model state."""
        ...

    def capabilities(self) -> frozenset[AdapterCapability]:
        """Declare optional evidence and execution capabilities."""
        ...

    def run(
        self,
        cases: Sequence[EvalCase],
        profile: RuntimeProfile,
    ) -> tuple[Observation, ...]:
        """Run cases in input order and return one paired observation per case."""
        ...
