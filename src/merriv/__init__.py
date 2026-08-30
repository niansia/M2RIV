"""Public Merriv contracts (installed from the ``merriv`` distribution)."""

from merriv.core.identity import build_local_snapshot, fingerprint, hash_artifact
from merriv.core.models import (
    ArtifactDigest,
    Claim,
    ClaimStrength,
    EvalCase,
    EvidenceAccess,
    EvidenceRef,
    ModelFamily,
    ModelRef,
    ModelSnapshot,
    Observation,
    RetentionMode,
    RunManifest,
    RuntimeProfile,
)

__all__ = [
    "ArtifactDigest",
    "Claim",
    "ClaimStrength",
    "EvalCase",
    "EvidenceAccess",
    "EvidenceRef",
    "ModelFamily",
    "ModelRef",
    "ModelSnapshot",
    "Observation",
    "RetentionMode",
    "RunManifest",
    "RuntimeProfile",
    "build_local_snapshot",
    "fingerprint",
    "hash_artifact",
]

__version__ = "0.1.0a2"
