"""Portable evidence produced by external backend comparison tools."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, FiniteFloat, StringConstraints, field_validator, model_validator

from m2riv.core.identity import fingerprint
from m2riv.core.models import (
    ContentId,
    Contract,
    RuntimeProfile,
    SafeCaseId,
    SafePluginName,
    SafePluginVersion,
)

SafeOutputName = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$"),
]


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

    schema_version: Literal["1.0.0"] = "1.0.0"
    id: ContentId
    comparator_name: SafePluginName
    comparator_version: SafePluginVersion
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
        if (self.peak_vram_mib is None) is not (self.vram_measurement == "unavailable"):
            raise ValueError("peak_vram_mib and vram_measurement must be reported together")
        return self


def create_backend_comparison_evidence(
    *,
    comparator_name: str,
    comparator_version: str,
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
        id=f"m2riv:sha256:{identifier}",
        comparator_name=comparator_name,
        comparator_version=comparator_version,
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
