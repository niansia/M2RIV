"""Public JSON Schema export."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from merriv.artifacts import ArtifactDiff, ArtifactProfile, NumericalDiff
from merriv.attestation import MCRInTotoStatement
from merriv.conformance import ConsumerConformanceReceipt, MCRConformanceResult
from merriv.core.models import (
    Claim,
    EvalCase,
    EvidenceRef,
    ModelRef,
    ModelSnapshot,
    Observation,
    RunManifest,
    RuntimeProfile,
)
from merriv.evidence import (
    BackendComparisonEvidence,
    BuildProvenanceEvidence,
    SnapshotArtifactManifest,
    ToolNativeEvidence,
)
from merriv.execution import ExecutorDescriptor
from merriv.gate import GateDecision, GatePolicy
from merriv.oci import MCRArtifactManifest
from merriv.planning import CompiledReleasePlan
from merriv.plugins import PluginManifest
from merriv.reports.models import (
    EvidenceManifest,
    EvidenceManifestRef,
    EvidenceSet,
    ModelChangeReport,
)
from merriv.reports.verify import MCRVerification
from merriv.target import TargetEvidenceManifest, TargetEvidenceVerification

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
    MCRInTotoStatement,
    MCRArtifactManifest,
    EvidenceSet,
    EvidenceManifestRef,
    EvidenceManifest,
    ModelChangeReport,
    MCRVerification,
    PluginManifest,
    ExecutorDescriptor,
    CompiledReleasePlan,
    ArtifactProfile,
    ArtifactDiff,
    NumericalDiff,
    ConsumerConformanceReceipt,
    MCRConformanceResult,
    BackendComparisonEvidence,
    ToolNativeEvidence,
    SnapshotArtifactManifest,
    BuildProvenanceEvidence,
    TargetEvidenceManifest,
    TargetEvidenceVerification,
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
