"""Public JSON Schema export."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from m2riv.artifacts import ArtifactDiff, ArtifactProfile, NumericalDiff
from m2riv.core.models import (
    Claim,
    EvalCase,
    EvidenceRef,
    ModelRef,
    ModelSnapshot,
    Observation,
    RunManifest,
    RuntimeProfile,
)
from m2riv.execution import ExecutorDescriptor
from m2riv.gate import GateDecision, GatePolicy
from m2riv.planning import CompiledReleasePlan
from m2riv.plugins import PluginManifest
from m2riv.reports.models import (
    EvidenceManifest,
    EvidenceManifestRef,
    EvidenceSet,
    ModelChangeReport,
)

PUBLIC_CONTRACTS: tuple[type[BaseModel], ...] = (
    ModelRef,
    RuntimeProfile,
    ModelSnapshot,
    EvalCase,
    Observation,
    EvidenceRef,
    Claim,
    RunManifest,
    GatePolicy,
    GateDecision,
    EvidenceSet,
    EvidenceManifestRef,
    EvidenceManifest,
    ModelChangeReport,
    PluginManifest,
    ExecutorDescriptor,
    CompiledReleasePlan,
    ArtifactProfile,
    ArtifactDiff,
    NumericalDiff,
)


def export_schemas(destination: Path) -> tuple[Path, ...]:
    """Write deterministic JSON Schema files for cross-language consumers."""
    destination.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    for contract in PUBLIC_CONTRACTS:
        target = destination / f"{contract.__name__}.schema.json"
        target.write_text(
            json.dumps(contract.model_json_schema(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        generated.append(target)
    return tuple(generated)
