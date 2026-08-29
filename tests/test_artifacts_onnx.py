# ruff: noqa: E402
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

# Optional dependency probes must run before importing ONNX-backed test helpers.
np = pytest.importorskip("numpy")
onnx = pytest.importorskip("onnx")
pytest.importorskip("onnxruntime")

from onnx import TensorProto, helper, numpy_helper

from m2riv.adapters import OnnxRuntimeAdapter, OnnxRuntimeError
from m2riv.artifacts import (
    ArtifactComponent,
    ArtifactFormat,
    ArtifactInspectionError,
    compare_artifacts,
    compare_onnx_numerics,
    inspect_artifact,
)
from m2riv.cli import app
from m2riv.core.models import EvalCase, ModelFamily, RuntimeProfile


def _model(
    path: Path, *, half: bool = False, opset: int = 17, weight_scale: float = 1.0
) -> Path:
    dtype = np.float16 if half else np.float32
    tensor_type = TensorProto.FLOAT16 if half else TensorProto.FLOAT
    weights = numpy_helper.from_array(np.eye(2, dtype=dtype) * weight_scale, "weights")
    graph = helper.make_graph(
        [
            helper.make_node("MatMul", ["input", "weights"], ["scores"]),
            helper.make_node("ArgMax", ["scores"], ["label"], axis=1, keepdims=0),
        ],
        "identity-classifier",
        [helper.make_tensor_value_info("input", tensor_type, [None, 2])],
        [helper.make_tensor_value_info("label", TensorProto.INT64, [None])],
        [weights],
    )
    model = helper.make_model(
        graph,
        opset_imports=[helper.make_opsetid("", opset)],
        producer_name="m2riv-test",
    )
    model.ir_version = 9
    onnx.checker.check_model(model)
    onnx.save_model(model, path)
    return path


def test_onnx_profile_and_diff_expose_structure_not_weights(tmp_path: Path) -> None:
    fp32 = inspect_artifact(_model(tmp_path / "fp32.onnx"))
    fp16 = inspect_artifact(_model(tmp_path / "fp16.onnx", half=True))

    assert fp32.onnx is not None
    assert fp32.onnx.node_count == 2
    assert fp32.onnx.parameter_count == 4
    assert fp32.onnx.quantization_format == "none"
    assert {item.name: item.count for item in fp32.onnx.initializer_dtype_counts} == {
        "FLOAT": 1
    }
    diff = compare_artifacts(fp32, fp16)
    assert diff.artifact_changed
    assert {item.name: item.delta for item in diff.initializer_dtype_changes} == {
        "FLOAT": -1,
        "FLOAT16": 1,
    }
    assert compare_artifacts(fp32, fp16).id == diff.id


def test_artifact_diff_handles_generic_files_and_opset_changes(tmp_path: Path) -> None:
    baseline_file = tmp_path / "baseline.bin"
    candidate_file = tmp_path / "candidate.bin"
    baseline_file.write_bytes(b"baseline")
    candidate_file.write_bytes(b"candidate-longer")
    generic = compare_artifacts(
        inspect_artifact(baseline_file), inspect_artifact(candidate_file)
    )

    assert generic.node_count_delta is None
    assert generic.size_delta_bytes == len(b"candidate-longer") - len(b"baseline")
    opset = compare_artifacts(
        inspect_artifact(_model(tmp_path / "opset17.onnx", opset=17)),
        inspect_artifact(_model(tmp_path / "opset18.onnx", opset=18)),
    )
    assert [(item.baseline, item.candidate) for item in opset.opset_changes] == [(17, 18)]


def test_directory_profile_hashes_sidecars_and_avoids_ambiguous_onnx(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    (artifact / "config.json").write_text('{"dtype":"float16"}', encoding="utf-8")
    (artifact / "tokenizer.json").write_text("{}", encoding="utf-8")
    _model(artifact / "a.onnx")
    _model(artifact / "b.onnx")

    profile = inspect_artifact(artifact)

    assert profile.format is ArtifactFormat.DIRECTORY
    assert profile.onnx is None
    assert {component.role for component in profile.components} == {
        "config",
        "model-onnx",
        "tokenizer",
    }


@pytest.mark.parametrize("relative_path", ["../escape", "/absolute", "C:/drive"])
def test_artifact_component_requires_portable_relative_path(relative_path: str) -> None:
    with pytest.raises(ValidationError, match="portable relative path"):
        ArtifactComponent(
            role="config",
            relative_path=relative_path,
            digest="0" * 64,
            size_bytes=1,
        )


def test_onnx_runtime_adapter_executes_cpu_cases(tmp_path: Path) -> None:
    adapter = OnnxRuntimeAdapter(
        _model(tmp_path / "model.onnx"), model_family=ModelFamily.CV
    )
    cases = (
        EvalCase(case_id="left", input=[2.0, 1.0], expected=0),
        EvalCase(case_id="right", input=[1.0, 2.0], expected=1),
    )

    observations = adapter.run(cases, RuntimeProfile(device="cpu", repetitions=2))

    assert [item.output for item in observations] == [0, 1]
    assert all(item.latency_ms is not None for item in observations)
    assert adapter.describe().model_family is ModelFamily.CV
    assert adapter.adapter_fingerprint


def test_numerical_diff_finds_first_intermediate_drift(tmp_path: Path) -> None:
    baseline = _model(tmp_path / "baseline-numeric.onnx")
    candidate = _model(tmp_path / "candidate-numeric.onnx", weight_scale=0.5)
    cases = (
        EvalCase(case_id="left", input=[2.0, 1.0]),
        EvalCase(case_id="right", input=[1.0, 2.0]),
    )

    result = compare_onnx_numerics(
        baseline,
        candidate,
        cases,
        absolute_tolerance=1e-8,
        relative_tolerance=1e-8,
    )

    assert result.first_divergent_tensor == "scores"
    scores = next(item for item in result.tensors if item.name == "scores")
    labels = next(item for item in result.tensors if item.name == "label")
    assert scores.max_abs_error == pytest.approx(1.0)
    assert not scores.within_tolerance
    assert labels.within_tolerance
    assert (
        compare_onnx_numerics(
            baseline,
            candidate,
            cases,
            absolute_tolerance=1e-8,
            relative_tolerance=1e-8,
        ).id
        == result.id
    )


def test_onnx_runtime_adapter_rejects_bad_configuration_and_inputs(tmp_path: Path) -> None:
    source = _model(tmp_path / "model.onnx")
    with pytest.raises(ValueError, match="between 1 and 256"):
        OnnxRuntimeAdapter(source, intra_op_threads=0)
    with pytest.raises(OnnxRuntimeError, match="requested ONNX input"):
        OnnxRuntimeAdapter(source, input_name="missing")
    with pytest.raises(OnnxRuntimeError, match="requested ONNX output"):
        OnnxRuntimeAdapter(source, output_name="missing")

    adapter = OnnxRuntimeAdapter(source)
    with pytest.raises(OnnxRuntimeError, match="mapping must match"):
        adapter.run(
            (EvalCase(case_id="mapped", input={"wrong": [1.0, 2.0]}),),
            RuntimeProfile(device="cpu"),
        )
    with pytest.raises(OnnxRuntimeError, match="rank does not match"):
        adapter.run(
            (EvalCase(case_id="rank", input=[[[1.0, 2.0]]]),),
            RuntimeProfile(device="cpu"),
        )
    with pytest.raises(OnnxRuntimeError, match="only supports the CPU"):
        adapter.run(
            (EvalCase(case_id="device", input=[1.0, 2.0]),),
            RuntimeProfile(device="cuda"),
        )


def test_onnx_runtime_failures_do_not_expose_native_error_text(tmp_path: Path) -> None:
    adapter = OnnxRuntimeAdapter(_model(tmp_path / "model.onnx"))

    class FailingSession:
        def run(self, outputs: object, inputs: object) -> object:
            raise RuntimeError("api-key=super-secret")

    adapter._session = FailingSession()  # type: ignore[assignment]
    with pytest.raises(OnnxRuntimeError) as captured:
        adapter.run(
            (EvalCase(case_id="case", input=[1.0, 2.0]),),
            RuntimeProfile(device="cpu"),
        )
    assert "super-secret" not in str(captured.value)


def test_onnx_adapter_rejects_non_onnx_artifact(tmp_path: Path) -> None:
    source = tmp_path / "weights.bin"
    source.write_bytes(b"not an ONNX graph")
    with pytest.raises(OnnxRuntimeError, match="exactly one inspectable ONNX"):
        OnnxRuntimeAdapter(source)


def test_onnx_adapter_rejects_external_tensor_data(tmp_path: Path) -> None:
    source = _model(tmp_path / "external.onnx")
    model = onnx.load_model(source)
    onnx.save_model(
        model,
        source,
        save_as_external_data=True,
        all_tensors_to_one_file=True,
        location="weights.bin",
        size_threshold=0,
    )

    assert inspect_artifact(source).onnx is not None
    assert inspect_artifact(source).onnx.uses_external_data
    with pytest.raises(OnnxRuntimeError, match="external ONNX tensor data"):
        OnnxRuntimeAdapter(source)


def test_onnx_inspection_is_bounded_and_secret_safe(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.onnx"
    malformed.write_bytes(b"api-key=super-secret-not-a-protobuf")

    with pytest.raises(ArtifactInspectionError) as captured:
        inspect_artifact(malformed)
    assert "super-secret" not in str(captured.value)
    with pytest.raises(ArtifactInspectionError, match="byte inspection limit"):
        inspect_artifact(_model(tmp_path / "bounded.onnx"), max_onnx_bytes=1)


def test_artifact_cli_outputs_public_contracts(tmp_path: Path) -> None:
    baseline = _model(tmp_path / "baseline.onnx")
    candidate = _model(tmp_path / "candidate.onnx", half=True)
    runner = CliRunner()

    inspected = runner.invoke(app, ["artifact", "inspect", str(baseline)])
    compared = runner.invoke(app, ["artifact", "diff", str(baseline), str(candidate)])

    assert inspected.exit_code == 0
    assert json.loads(inspected.stdout)["onnx"]["node_count"] == 2
    assert compared.exit_code == 0
    assert json.loads(compared.stdout)["artifact_changed"] is True


def test_numerical_diff_cli_reads_the_standard_suite(tmp_path: Path) -> None:
    baseline = _model(tmp_path / "baseline-cli-numeric.onnx")
    candidate = _model(tmp_path / "candidate-cli-numeric.onnx", weight_scale=0.5)
    suite = tmp_path / "numeric-suite.jsonl"
    suite.write_text(
        json.dumps({"case_id": "case", "input": [2.0, 1.0]}) + "\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        [
            "artifact",
            "numerical-diff",
            str(baseline),
            str(candidate),
            "--suite",
            str(suite),
        ],
    )

    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout)["first_divergent_tensor"] == "scores"


def test_artifact_cli_fails_before_hashing_over_budget_file(tmp_path: Path) -> None:
    artifact = tmp_path / "oversized.bin"
    artifact.write_bytes(b"12")
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["inspect", str(artifact), "--max-artifact-bytes", "1"],
    )

    assert result.exit_code == 3
    assert "byte budget" in result.stderr


def test_bisect_run_executes_onnx_checkpoints(tmp_path: Path) -> None:
    artifacts = (
        _model(tmp_path / "checkpoint-0.onnx"),
        _model(tmp_path / "checkpoint-1.onnx"),
        _model(tmp_path / "checkpoint-2.onnx", weight_scale=-1.0),
    )
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        "".join(
            json.dumps({"checkpoint": f"cp-{index}", "artifact": artifact.name}) + "\n"
            for index, artifact in enumerate(artifacts)
        ),
        encoding="utf-8",
    )
    suite = tmp_path / "suite.jsonl"
    suite.write_text(
        "".join(
            json.dumps({"case_id": case_id, "input": inputs, "expected": expected}) + "\n"
            for case_id, inputs, expected in (
                ("zero", [1.0, 0.0], 0),
                ("one", [0.0, 1.0], 1),
            )
        ),
        encoding="utf-8",
    )
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        """schema_version: 1.0.0
policy_id: onnx-bisect
rules:
  - rule_id: accuracy
    metric: accuracy
    margin: 0.1
    min_pairs: 2
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        [
            "bisect-run",
            str(manifest),
            "--suite",
            str(suite),
            "--policy",
            str(policy),
            "--adapter",
            "onnx",
            "--output",
            str(tmp_path / "run"),
            "--resamples",
            "100",
        ],
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["first_failing_checkpoint"] == "cp-2"
    assert {item["status"] for item in payload["executed_checkpoints"]} == {
        "pass",
        "block",
    }
