"""Portable contracts for deployment-artifact inspection and comparison."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, FiniteFloat, StringConstraints, field_validator

from merriv.core.models import ArtifactDigest, ContentId, Contract, Digest

SafeName = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,255}$"),
]
SafeDimension = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9_?][A-Za-z0-9._?+-]{0,127}$"),
]


class ArtifactFormat(StrEnum):
    ONNX = "onnx"
    DIRECTORY = "directory"
    FILE = "file"


class ArtifactComponent(Contract):
    role: SafeName
    relative_path: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    digest: Digest
    size_bytes: int = Field(ge=0)

    @field_validator("relative_path")
    @classmethod
    def portable_relative_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        parts = normalized.split("/")
        if (
            normalized.startswith("/")
            or any(":" in part for part in parts)
            or any(part in {"", ".", ".."} for part in parts)
            or any(not character.isprintable() for character in normalized)
        ):
            raise ValueError("component path must be a safe portable relative path")
        return normalized


class OnnxOpset(Contract):
    domain: SafeName
    version: int = Field(ge=0)


class OnnxCount(Contract):
    name: SafeName
    count: int = Field(ge=0)


class OnnxTensorSpec(Contract):
    name: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    element_type: SafeName
    shape: tuple[SafeDimension, ...] = Field(default=(), max_length=32)

    @field_validator("name")
    @classmethod
    def printable_name(cls, value: str) -> str:
        if any(not character.isprintable() for character in value):
            raise ValueError("ONNX tensor names must contain printable characters")
        return value


class OnnxGraphSummary(Contract):
    ir_version: int = Field(ge=0)
    producer_name: Annotated[str, StringConstraints(max_length=256)] = ""
    producer_version: Annotated[str, StringConstraints(max_length=128)] = ""
    model_version: int = Field(ge=0)
    opsets: tuple[OnnxOpset, ...] = Field(default=(), max_length=64)
    node_count: int = Field(ge=0)
    initializer_count: int = Field(ge=0)
    parameter_count: int = Field(ge=0)
    operator_counts: tuple[OnnxCount, ...] = Field(default=(), max_length=4096)
    initializer_dtype_counts: tuple[OnnxCount, ...] = Field(default=(), max_length=128)
    inputs: tuple[OnnxTensorSpec, ...] = Field(default=(), max_length=256)
    outputs: tuple[OnnxTensorSpec, ...] = Field(default=(), max_length=256)
    uses_external_data: bool = False
    quantization_format: Literal["none", "qdq", "qoperator", "mixed"] = "none"
    metadata_fingerprint: Digest

    @field_validator("producer_name", "producer_version")
    @classmethod
    def printable_metadata(cls, value: str) -> str:
        if any(not character.isprintable() for character in value):
            raise ValueError("ONNX producer metadata must be printable")
        return value


class ArtifactProfile(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    id: ContentId
    format: ArtifactFormat
    artifact: ArtifactDigest
    components: tuple[ArtifactComponent, ...] = Field(default=(), max_length=128)
    onnx: OnnxGraphSummary | None = None


class NamedCountChange(Contract):
    name: SafeName
    baseline: int = Field(ge=0)
    candidate: int = Field(ge=0)
    delta: int


class OpsetChange(Contract):
    domain: SafeName
    baseline: int | None = Field(default=None, ge=0)
    candidate: int | None = Field(default=None, ge=0)


class ArtifactDiff(Contract):
    schema_version: Literal["1.0.0"] = "1.0.0"
    id: ContentId
    baseline_profile_id: ContentId
    candidate_profile_id: ContentId
    artifact_changed: bool
    format_changed: bool
    size_delta_bytes: int
    file_count_delta: int
    changed_components: tuple[SafeName, ...] = Field(default=(), max_length=128)
    opset_changes: tuple[OpsetChange, ...] = Field(default=(), max_length=64)
    operator_changes: tuple[NamedCountChange, ...] = Field(default=(), max_length=4096)
    initializer_dtype_changes: tuple[NamedCountChange, ...] = Field(default=(), max_length=128)
    node_count_delta: int | None = None
    initializer_count_delta: int | None = None
    parameter_count_delta: int | None = None
    inputs_changed: bool | None = None
    outputs_changed: bool | None = None
    external_data_changed: bool | None = None
    quantization_format_changed: bool | None = None


class TensorNumericalDiff(Contract):
    """Aggregated drift for one tensor shared by two executed ONNX graphs."""

    name: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    baseline_dtype: SafeName
    candidate_dtype: SafeName
    shape: tuple[int, ...] | None = Field(default=None, max_length=32)
    element_count: int = Field(ge=1)
    max_abs_error: FiniteFloat = Field(ge=0)
    mean_abs_error: FiniteFloat = Field(ge=0)
    rmse: FiniteFloat = Field(ge=0)
    max_relative_error: FiniteFloat = Field(ge=0)
    cosine_similarity: FiniteFloat = Field(ge=-1, le=1)
    within_tolerance: bool

    @field_validator("name")
    @classmethod
    def printable_name(cls, value: str) -> str:
        if any(not character.isprintable() for character in value):
            raise ValueError("tensor names must contain printable characters")
        return value


class NumericalDiff(Contract):
    """Execution-derived per-tensor drift between two self-contained ONNX models."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    id: ContentId
    baseline_profile_id: ContentId
    candidate_profile_id: ContentId
    case_count: int = Field(ge=1)
    absolute_tolerance: FiniteFloat = Field(ge=0)
    relative_tolerance: FiniteFloat = Field(ge=0)
    baseline_only_tensors: tuple[str, ...] = Field(default=(), max_length=4096)
    candidate_only_tensors: tuple[str, ...] = Field(default=(), max_length=4096)
    tensors: tuple[TensorNumericalDiff, ...] = Field(min_length=1, max_length=4096)
    first_divergent_tensor: str | None = None
