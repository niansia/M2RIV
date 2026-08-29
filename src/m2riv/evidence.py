"""Portable evidence contracts for external tools, builds, and target runs."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal

from pydantic import Field, FiniteFloat, StringConstraints, field_validator, model_validator

from m2riv.core.identity import fingerprint, hash_artifact
from m2riv.core.models import (
    ArtifactDigest,
    ContentId,
    Contract,
    Digest,
    ModelSnapshot,
    RuntimeProfile,
    SafeCaseId,
    SafePluginName,
    SafePluginVersion,
)

SafeOutputName = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$"),
]


def _safe_bundle_uri(value: str) -> str:
    normalized = value.replace("\\", "/")
    relative = PurePosixPath(normalized)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(
            part in {"", ".", ".."}
            or ":" in part
            or any(not character.isprintable() for character in part)
            for part in relative.parts
        )
    ):
        raise ValueError("evidence URI must be a safe relative bundle path")
    return relative.as_posix()


class FileDigestBinding(Contract):
    """Portable location plus digest for one retained regular file."""

    uri: Annotated[str, StringConstraints(min_length=1, max_length=2048)]
    sha256: Digest
    size_bytes: int = Field(ge=0)
    logical_name: Annotated[str, StringConstraints(min_length=1, max_length=256)]

    @field_validator("uri")
    @classmethod
    def uri_is_safe_relative_path(cls, value: str) -> str:
        return _safe_bundle_uri(value)


def _binding_identity(binding: FileDigestBinding) -> dict[str, Any]:
    return binding.model_dump(mode="python", exclude={"uri"})


class ToolNativeEvidence(Contract):
    """Opaque vendor/tool evidence retained byte-for-byte and content-bound."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    id: ContentId
    producer_name: SafePluginName
    producer_version: SafePluginVersion
    media_type: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    purpose: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    body: FileDigestBinding
    exit_code: int | None = Field(default=None, ge=0, le=255)
    runner_names: tuple[SafeOutputName, ...] = Field(default=(), max_length=32)
    limitations: tuple[str, ...] = Field(default=(), max_length=64)


def create_tool_native_evidence(
    source: str | Path,
    *,
    uri: str,
    producer_name: str,
    producer_version: str,
    media_type: str,
    purpose: str,
    exit_code: int | None = None,
    runner_names: tuple[str, ...] = (),
    limitations: tuple[str, ...] = (),
) -> ToolNativeEvidence:
    """Bind one opaque tool-native file without interpreting its payload."""
    digest = hash_artifact(source)
    if digest.file_count != 1:
        raise ValueError("tool-native evidence must be one regular file")
    binding = FileDigestBinding(
        uri=uri,
        sha256=digest.digest,
        size_bytes=digest.size_bytes,
        logical_name=digest.logical_name or Path(source).name,
    )
    payload = {
        "producer_name": producer_name,
        "producer_version": producer_version,
        "media_type": media_type,
        "purpose": purpose,
        "body": _binding_identity(binding),
        "exit_code": exit_code,
        "runner_names": runner_names,
        "limitations": limitations,
    }
    identifier = fingerprint(payload, namespace="tool-native-evidence")
    return ToolNativeEvidence(
        id=f"mcr:sha256:{identifier}",
        producer_name=producer_name,
        producer_version=producer_version,
        media_type=media_type,
        purpose=purpose,
        body=binding,
        exit_code=exit_code,
        runner_names=runner_names,
        limitations=limitations,
    )


class SnapshotArtifactManifest(Contract):
    """Bind a snapshot identity to retained artifact bytes."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    id: ContentId
    snapshot: ModelSnapshot
    artifacts: tuple[FileDigestBinding, ...] = Field(min_length=1, max_length=1024)

    @model_validator(mode="after")
    def bindings_match_snapshot_artifacts(self) -> SnapshotArtifactManifest:
        expected = sorted(
            (item.digest, item.size_bytes, item.logical_name)
            for item in self.snapshot.artifact_hashes
        )
        observed = sorted(
            (item.sha256, item.size_bytes, item.logical_name) for item in self.artifacts
        )
        if observed != expected:
            raise ValueError("snapshot artifact bindings must match snapshot digests")
        return self


def create_snapshot_artifact_manifest(
    snapshot: ModelSnapshot,
    bindings: tuple[FileDigestBinding, ...],
) -> SnapshotArtifactManifest:
    payload = {
        # The source URI is a locator and may change when the same bundle moves.
        "snapshot": snapshot.model_dump(mode="python", exclude={"source"}),
        "artifacts": tuple(_binding_identity(item) for item in bindings),
    }
    identifier = fingerprint(payload, namespace="snapshot-artifact-manifest")
    return SnapshotArtifactManifest(
        id=f"mcr:sha256:{identifier}", snapshot=snapshot, artifacts=bindings
    )


class BuildProvenanceEvidence(Contract):
    """Content-addressed build recipe and artifact transition evidence."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    id: ContentId
    build_name: SafeCaseId
    builder_name: SafePluginName
    builder_version: SafePluginVersion
    source_commit: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{40,64}$")] | None = None
    input_artifacts: tuple[ArtifactDigest, ...] = Field(min_length=1, max_length=128)
    output_artifacts: tuple[ArtifactDigest, ...] = Field(min_length=1, max_length=128)
    output_snapshot_id: ContentId
    parameters: dict[str, Any] = Field(default_factory=dict)
    calibration_cohort_digest: Digest | None = None
    parent_build_id: ContentId | None = None
    limitations: tuple[str, ...] = Field(default=(), max_length=64)


def create_build_provenance_evidence(
    *,
    build_name: str,
    builder_name: str,
    builder_version: str,
    input_artifacts: tuple[ArtifactDigest, ...],
    output_artifacts: tuple[ArtifactDigest, ...],
    output_snapshot_id: str,
    source_commit: str | None = None,
    parameters: dict[str, Any] | None = None,
    calibration_cohort_digest: str | None = None,
    parent_build_id: str | None = None,
    limitations: tuple[str, ...] = (),
) -> BuildProvenanceEvidence:
    payload = {
        "build_name": build_name,
        "builder_name": builder_name,
        "builder_version": builder_version,
        "source_commit": source_commit,
        "input_artifacts": input_artifacts,
        "output_artifacts": output_artifacts,
        "output_snapshot_id": output_snapshot_id,
        "parameters": parameters or {},
        "calibration_cohort_digest": calibration_cohort_digest,
        "parent_build_id": parent_build_id,
        "limitations": limitations,
    }
    identifier = fingerprint(payload, namespace="build-provenance-evidence")
    return BuildProvenanceEvidence(
        id=f"mcr:sha256:{identifier}",
        build_name=build_name,
        builder_name=builder_name,
        builder_version=builder_version,
        source_commit=source_commit,
        input_artifacts=input_artifacts,
        output_artifacts=output_artifacts,
        output_snapshot_id=output_snapshot_id,
        parameters=parameters or {},
        calibration_cohort_digest=calibration_cohort_digest,
        parent_build_id=parent_build_id,
        limitations=limitations,
    )


class BackendCaseComparison(Contract):
    """One comparator-owned case result with optional measured runtimes."""

    case_id: SafeCaseId
    output_matches: dict[SafeOutputName, bool] = Field(min_length=1, max_length=256)
    baseline_latency_ms: FiniteFloat | None = Field(default=None, ge=0)
    candidate_latency_ms: FiniteFloat | None = Field(default=None, ge=0)

    @field_validator("output_matches")
    @classmethod
    def output_names_are_unique_after_string_normalization(
        cls, value: dict[str, bool]
    ) -> dict[str, bool]:
        if len(value) != len(set(value)):
            raise ValueError("backend comparison output names must be unique")
        return value


class BackendComparisonEvidence(Contract):
    """Bounded, content-addressed backend parity and performance evidence."""

    schema_version: Literal["0.2.0"] = "0.2.0"
    id: ContentId
    comparator_name: SafePluginName
    comparator_version: SafePluginVersion
    oracle: Literal["comparator-native"] = "comparator-native"
    comparator_exit_code: int = Field(ge=0, le=1)
    baseline_runner: SafeOutputName
    candidate_runner: SafeOutputName
    tool_native_evidence_id: ContentId
    baseline_snapshot_id: ContentId
    candidate_snapshot_id: ContentId
    absolute_tolerance: FiniteFloat = Field(ge=0)
    relative_tolerance: FiniteFloat = Field(ge=0)
    case_count: int = Field(ge=1, le=100_000)
    matched_case_count: int = Field(ge=0)
    comparisons: tuple[BackendCaseComparison, ...] = Field(min_length=1, max_length=100_000)
    runtime_profile: RuntimeProfile
    peak_vram_mib: FiniteFloat | None = Field(default=None, ge=0)
    vram_measurement: Literal["nvml-process-peak", "unavailable"] = "unavailable"
    limitations: tuple[str, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def counts_and_measurements_match(self) -> BackendComparisonEvidence:
        if self.case_count != len(self.comparisons):
            raise ValueError("backend comparison case_count must match comparisons")
        observed_matches = sum(all(item.output_matches.values()) for item in self.comparisons)
        if self.matched_case_count != observed_matches:
            raise ValueError("matched_case_count must match per-case output results")
        expected_exit = 0 if observed_matches == self.case_count else 1
        if self.comparator_exit_code != expected_exit:
            raise ValueError("comparator exit code must match the native parity verdict")
        if (self.peak_vram_mib is None) is not (self.vram_measurement == "unavailable"):
            raise ValueError("peak_vram_mib and vram_measurement must be reported together")
        return self


def create_backend_comparison_evidence(
    *,
    comparator_name: str,
    comparator_version: str,
    comparator_exit_code: int,
    baseline_runner: str,
    candidate_runner: str,
    tool_native_evidence_id: str,
    baseline_snapshot_id: str,
    candidate_snapshot_id: str,
    absolute_tolerance: float,
    relative_tolerance: float,
    comparisons: tuple[BackendCaseComparison, ...],
    runtime_profile: RuntimeProfile,
    peak_vram_mib: float | None = None,
    vram_measurement: Literal["nvml-process-peak", "unavailable"] = "unavailable",
    limitations: tuple[str, ...] = (),
) -> BackendComparisonEvidence:
    """Create deterministic external comparator evidence."""
    matched_case_count = sum(all(item.output_matches.values()) for item in comparisons)
    payload = {
        "comparator_name": comparator_name,
        "comparator_version": comparator_version,
        "oracle": "comparator-native",
        "comparator_exit_code": comparator_exit_code,
        "baseline_runner": baseline_runner,
        "candidate_runner": candidate_runner,
        "tool_native_evidence_id": tool_native_evidence_id,
        "baseline_snapshot_id": baseline_snapshot_id,
        "candidate_snapshot_id": candidate_snapshot_id,
        "absolute_tolerance": absolute_tolerance,
        "relative_tolerance": relative_tolerance,
        "case_count": len(comparisons),
        "matched_case_count": matched_case_count,
        "comparisons": comparisons,
        "runtime_profile": runtime_profile,
        "peak_vram_mib": peak_vram_mib,
        "vram_measurement": vram_measurement,
        "limitations": limitations,
    }
    identifier = fingerprint(payload, namespace="backend-comparison-evidence")
    return BackendComparisonEvidence(
        id=f"mcr:sha256:{identifier}",
        comparator_name=comparator_name,
        comparator_version=comparator_version,
        oracle="comparator-native",
        comparator_exit_code=comparator_exit_code,
        baseline_runner=baseline_runner,
        candidate_runner=candidate_runner,
        tool_native_evidence_id=tool_native_evidence_id,
        baseline_snapshot_id=baseline_snapshot_id,
        candidate_snapshot_id=candidate_snapshot_id,
        absolute_tolerance=absolute_tolerance,
        relative_tolerance=relative_tolerance,
        case_count=len(comparisons),
        matched_case_count=matched_case_count,
        comparisons=comparisons,
        runtime_profile=runtime_profile,
        peak_vram_mib=peak_vram_mib,
        vram_measurement=vram_measurement,
        limitations=limitations,
    )
