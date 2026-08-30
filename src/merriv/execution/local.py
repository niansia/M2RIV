"""Dependency-free in-process execution backend."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from merriv.adapters import ModelAdapter
from merriv.core.identity import fingerprint
from merriv.core.models import EvalCase, Observation, RuntimeProfile
from merriv.execution.base import ExecutorDescriptor

_LOCAL_CONFIG_FINGERPRINT = fingerprint(
    {"executor": "local", "version": "1.0.0", "mode": "in-process"},
    namespace="executor-config",
)
_LOCAL_DESCRIPTOR = ExecutorDescriptor(
    executor_id="merriv.local",
    version="1.0.0",
    config_fingerprint=_LOCAL_CONFIG_FINGERPRINT,
    capabilities=frozenset({"in_process"}),
)
LOCAL_EXECUTOR_FINGERPRINT = fingerprint(_LOCAL_DESCRIPTOR, namespace="executor-cache-identity")


@dataclass(frozen=True, slots=True)
class LocalExecutor:
    """Call an adapter in-process; intended for trusted adapter implementations."""

    def describe(self) -> ExecutorDescriptor:
        return _LOCAL_DESCRIPTOR

    def execute(
        self,
        adapter: ModelAdapter,
        cases: Sequence[EvalCase],
        profile: RuntimeProfile,
    ) -> tuple[Observation, ...]:
        return adapter.run(cases, profile)
