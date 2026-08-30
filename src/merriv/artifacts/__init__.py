"""Deployment-artifact inspection and semantic diffing."""

from merriv.artifacts.diff import compare_artifacts
from merriv.artifacts.inspector import (
    MAX_ONNX_BYTES,
    ArtifactInspectionError,
    inspect_artifact,
)
from merriv.artifacts.models import (
    ArtifactComponent,
    ArtifactDiff,
    ArtifactFormat,
    ArtifactProfile,
    NamedCountChange,
    NumericalDiff,
    OnnxCount,
    OnnxGraphSummary,
    OnnxOpset,
    OnnxTensorSpec,
    OpsetChange,
    TensorNumericalDiff,
)
from merriv.artifacts.numerical import (
    MAX_NUMERICAL_CASES,
    NumericalDiffError,
    compare_onnx_numerics,
)
from merriv.core.identity import (
    MAX_ARTIFACT_BYTES,
    MAX_ARTIFACT_ENTRIES,
    MAX_ARTIFACT_FILE_BYTES,
)

__all__ = [
    "MAX_ARTIFACT_BYTES",
    "MAX_ARTIFACT_ENTRIES",
    "MAX_ARTIFACT_FILE_BYTES",
    "MAX_NUMERICAL_CASES",
    "MAX_ONNX_BYTES",
    "ArtifactComponent",
    "ArtifactDiff",
    "ArtifactFormat",
    "ArtifactInspectionError",
    "ArtifactProfile",
    "NamedCountChange",
    "NumericalDiff",
    "NumericalDiffError",
    "OnnxCount",
    "OnnxGraphSummary",
    "OnnxOpset",
    "OnnxTensorSpec",
    "OpsetChange",
    "TensorNumericalDiff",
    "compare_artifacts",
    "compare_onnx_numerics",
    "inspect_artifact",
]
