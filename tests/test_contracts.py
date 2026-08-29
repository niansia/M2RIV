from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, ValidationError

from m2riv.artifacts import OnnxGraphSummary, OnnxTensorSpec, TensorNumericalDiff
from m2riv.core.identity import fingerprint
from m2riv.core.models import (
    Claim,
    ClaimStrength,
    EvalCase,
    EvidenceRef,
    ModelRef,
    Observation,
    RetentionMode,
    RunManifest,
    RuntimeProfile,
)


def content_id(label: str) -> str:
    return f"m2riv:sha256:{fingerprint(label, namespace='test')}"


@pytest.mark.parametrize(
    "model",
    [
        ModelRef(uri="hf://org/model@v1"),
        EvalCase(case_id="case-1", input={"prompt": "hello"}, tags={"smoke"}),
        EvidenceRef(id=content_id("evidence"), kind="observation"),
        Observation(
            id=content_id("observation"),
            snapshot_id=content_id("snapshot"),
            case_id="case-1",
            output={"answer": 42},
            output_digest=fingerprint({"answer": 42}, namespace="output"),
            retention=RetentionMode.FULL,
            created_at=datetime(2026, 8, 28, tzinfo=UTC),
        ),
        Claim(
            id=content_id("claim"),
            claim_type="behavioral-regression",
            statement="Candidate regressed on the critical slice.",
            strength=ClaimStrength.STATISTICAL,
            evidence=(EvidenceRef(id=content_id("evidence-2"), kind="diff"),),
        ),
        RunManifest(
            run_id=content_id("run"),
            baseline_snapshot_id=content_id("baseline"),
            candidate_snapshot_ids=(content_id("candidate"),),
            suite_fingerprint=fingerprint("suite", namespace="suite"),
            config_fingerprint=fingerprint("config", namespace="config"),
            created_at=datetime(2026, 8, 28, tzinfo=UTC),
        ),
    ],
)
def test_json_round_trip(model: BaseModel) -> None:
    assert type(model).model_validate_json(model.model_dump_json()) == model


def test_contracts_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ModelRef.model_validate({"uri": "./model", "surprise": True})


def test_observation_requires_timezone() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        Observation(
            id=content_id("observation"),
            snapshot_id=content_id("snapshot"),
            case_id="case-1",
            output_digest=fingerprint(None, namespace="output"),
            created_at=datetime(2026, 8, 28),
        )


def test_fingerprints_are_domain_separated() -> None:
    assert fingerprint("same", namespace="suite") != fingerprint("same", namespace="config")


def test_source_runtime_and_manifest_provenance_rejects_ambiguous_values() -> None:
    for uri in ("   ", "model\0revision"):
        with pytest.raises(ValidationError):
            ModelRef(uri=uri)
    with pytest.raises(ValidationError, match="credentials"):
        RuntimeProfile(parameters={"items": [{"authorization": "secret"}]})
    with pytest.raises(ValidationError, match="timezone-aware"):
        RunManifest(
            run_id=content_id("naive-run"),
            baseline_snapshot_id=content_id("naive-baseline"),
            candidate_snapshot_ids=(content_id("naive-candidate"),),
            suite_fingerprint="1" * 64,
            config_fingerprint="2" * 64,
            created_at=datetime(2026, 8, 29),
        )


def test_onnx_contracts_reject_control_characters() -> None:
    with pytest.raises(ValidationError, match="tensor names"):
        OnnxTensorSpec(name="bad\nname", element_type="FLOAT")
    with pytest.raises(ValidationError, match="producer metadata"):
        OnnxGraphSummary(
            ir_version=1,
            producer_name="bad\nproducer",
            model_version=1,
            node_count=0,
            initializer_count=0,
            parameter_count=0,
            metadata_fingerprint="3" * 64,
        )
    with pytest.raises(ValidationError, match="tensor names"):
        TensorNumericalDiff(
            name="bad\ntensor",
            baseline_dtype="float32",
            candidate_dtype="float32",
            element_count=1,
            max_abs_error=0,
            mean_abs_error=0,
            rmse=0,
            max_relative_error=0,
            cosine_similarity=1,
            within_tolerance=True,
        )
