"""Execution-driven regression localization over ordered model artifacts."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from m2riv.adapters import ModelAdapter
from m2riv.bisect.engine import BisectMode, BisectResult, bisect_regression
from m2riv.bisect.manifest import CheckpointArtifact
from m2riv.core.models import EvalCase, RuntimeProfile
from m2riv.engine import ObservationCache
from m2riv.gate import GatePolicy, GateStatus
from m2riv.pipeline import compare_exact_match
from m2riv.reports import write_report_bundle

AdapterFactory = Callable[
    [CheckpointArtifact, Literal["baseline", "candidate"]], tuple[ModelAdapter, str]
]


@dataclass(frozen=True, slots=True)
class ExecutedCheckpoint:
    index: int
    checkpoint: str
    artifact: Path
    status: GateStatus
    report_id: str
    report_directory: Path


@dataclass(frozen=True, slots=True)
class ExecutionDrivenBisect:
    result: BisectResult
    checkpoints: tuple[ExecutedCheckpoint, ...]


def execute_bisect(
    records: Sequence[CheckpointArtifact],
    *,
    adapter_factory: AdapterFactory,
    cases: Sequence[EvalCase],
    policy: GatePolicy,
    cache: ObservationCache,
    destination: Path,
    profile: RuntimeProfile | None = None,
    slice_keys: Sequence[str] = (),
    mode: BisectMode | str = BisectMode.MONOTONIC,
    sparse_points: int = 7,
    resamples: int = 2_000,
    confidence_level: float = 0.95,
) -> ExecutionDrivenBisect:
    """Evaluate only the checkpoints requested by the bisect strategy.

    Artifact manifests contain paths, never command strings. Execution remains
    inside a caller-supplied adapter boundary, so adding a new runtime does not
    grant shell execution to untrusted manifest content.
    """
    ordered = tuple(records)
    if not ordered:
        raise ValueError("execution-driven bisect requires at least one checkpoint")
    baseline, baseline_fingerprint = adapter_factory(ordered[0], "baseline")
    runtime_profile = profile or RuntimeProfile()
    completed: dict[int, ExecutedCheckpoint] = {}

    def evaluate(index: int) -> GateStatus:
        record = ordered[index]
        candidate, candidate_fingerprint = adapter_factory(record, "candidate")
        comparison = compare_exact_match(
            baseline=baseline,
            candidate=candidate,
            cases=cases,
            policy=policy,
            cache=cache,
            profile=runtime_profile,
            slice_keys=slice_keys,
            baseline_adapter_fingerprint=baseline_fingerprint,
            candidate_adapter_fingerprint=candidate_fingerprint,
            resamples=resamples,
            confidence_level=confidence_level,
        )
        report_directory = destination / "checkpoints" / f"{index:06d}"
        write_report_bundle(
            comparison.report,
            report_directory,
            release_plan=comparison.plan,
            evidence_manifest=comparison.evidence_manifest,
        )
        completed[index] = ExecutedCheckpoint(
            index=index,
            checkpoint=record.checkpoint,
            artifact=record.artifact,
            status=comparison.gate.status,
            report_id=comparison.report.id,
            report_directory=report_directory,
        )
        return comparison.gate.status

    result = bisect_regression(
        len(ordered),
        evaluate,
        mode=mode,
        sparse_points=sparse_points,
    )
    return ExecutionDrivenBisect(
        result=result,
        checkpoints=tuple(completed[index] for index in sorted(completed)),
    )
