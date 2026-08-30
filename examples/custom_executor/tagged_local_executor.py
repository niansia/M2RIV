"""Minimal executor plugin shape; replace execute() with remote dispatch."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from merriv.adapters import ModelAdapter
from merriv.core.identity import fingerprint
from merriv.core.models import EvalCase, Observation, RuntimeProfile
from merriv.execution import ExecutorDescriptor
from merriv.plugins import PluginKind, PluginManifest, PluginRegistry


@dataclass(frozen=True, slots=True)
class TaggedLocalExecutor:
    worker_pool: str

    @property
    def config_fingerprint(self) -> str:
        return fingerprint(
            {"worker_pool": self.worker_pool, "mode": "example-in-process"},
            namespace="example-executor-config",
        )

    def describe(self) -> ExecutorDescriptor:
        return ExecutorDescriptor(
            executor_id="example.tagged-local",
            version="0.1.0",
            config_fingerprint=self.config_fingerprint,
            capabilities=frozenset({"in_process"}),
        )

    def execute(
        self,
        adapter: ModelAdapter,
        cases: Sequence[EvalCase],
        profile: RuntimeProfile,
    ) -> tuple[Observation, ...]:
        return adapter.run(cases, profile)


def register(registry: PluginRegistry, *, worker_pool: str) -> TaggedLocalExecutor:
    executor = TaggedLocalExecutor(worker_pool)
    manifest = PluginManifest(
        name="example.tagged-local-executor",
        version="0.1.0",
        kind=PluginKind.EXECUTOR,
        config_fingerprint=executor.config_fingerprint,
        capabilities=frozenset({"in_process"}),
    )
    registry.register_executor(manifest, executor)
    return executor
