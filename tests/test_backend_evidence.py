from __future__ import annotations

import pytest
from pydantic import ValidationError

from m2riv.core.models import RuntimeProfile
from m2riv.evidence import (
    BackendCaseComparison,
    BackendComparisonEvidence,
    create_backend_comparison_evidence,
)

SNAPSHOT_A = "mcr:sha256:" + "a" * 64
SNAPSHOT_B = "mcr:sha256:" + "b" * 64


def _evidence() -> BackendComparisonEvidence:
    comparisons = (
        BackendCaseComparison(
            case_id="case-1",
            output_matches={"logits": True},
            baseline_latency_ms=1.0,
            candidate_latency_ms=0.8,
        ),
        BackendCaseComparison(
            case_id="case-2",
            output_matches={"logits": False},
            baseline_latency_ms=1.1,
            candidate_latency_ms=0.9,
        ),
    )
    return create_backend_comparison_evidence(
        comparator_name="nvidia.polygraphy",
        comparator_version="0.53.4",
        comparator_exit_code=1,
        baseline_runner="onnxrt-runner",
        candidate_runner="trt-runner",
        tool_native_evidence_id="mcr:sha256:" + "c" * 64,
        baseline_snapshot_id=SNAPSHOT_A,
        candidate_snapshot_id=SNAPSHOT_B,
        absolute_tolerance=0.05,
        relative_tolerance=0.01,
        comparisons=comparisons,
        runtime_profile=RuntimeProfile(framework="TensorRT", device="gpu", dtype="int8"),
        peak_vram_mib=512.0,
        vram_measurement="nvml-process-peak",
        limitations=("target-specific engine",),
    )


def test_backend_evidence_is_stable_and_counts_complete_matches() -> None:
    first = _evidence()
    second = _evidence()
    assert first.id == second.id
    assert first.case_count == 2
    assert first.matched_case_count == 1
    assert BackendComparisonEvidence.model_validate_json(first.model_dump_json()) == first


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"case_count": 1}, "case_count"),
        ({"matched_case_count": 2}, "matched_case_count"),
        ({"peak_vram_mib": None}, "reported together"),
    ],
)
def test_backend_evidence_rejects_inconsistent_summary_fields(
    updates: dict[str, object], message: str
) -> None:
    payload = _evidence().model_dump(mode="python")
    payload.update(updates)
    with pytest.raises(ValidationError, match=message):
        BackendComparisonEvidence.model_validate(payload)
