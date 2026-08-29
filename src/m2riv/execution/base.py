"""Execution-fabric boundary independent of model adapters and release semantics."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Protocol, runtime_checkable

from pydantic import Field, StringConstraints

from m2riv.adapters import ModelAdapter
from m2riv.core.models import Contract, Digest, EvalCase, Observation, RuntimeProfile

SafeExecutorId = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"),
]
SafeExecutorVersion = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9.+_-]{0,63}$"),
]
SafeExecutorCapability = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"),
]


class ExecutorDescriptor(Contract):
    """Non-secret executor identity that participates in cache safety."""

    executor_id: SafeExecutorId
    version: SafeExecutorVersion
    config_fingerprint: Digest
    capabilities: frozenset[SafeExecutorCapability] = Field(
        default_factory=frozenset, max_length=64
    )


@runtime_checkable
class ExecutionBackend(Protocol):
    """Run an adapter without owning pairing, cache, statistics, or gate semantics."""

    def describe(self) -> ExecutorDescriptor:
        """Return immutable, non-secret execution identity."""
        ...

    def execute(
        self,
        adapter: ModelAdapter,
        cases: Sequence[EvalCase],
        profile: RuntimeProfile,
    ) -> tuple[Observation, ...]:
        """Execute requested cases and return raw observations."""
        ...
