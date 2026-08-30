"""Build and gate a real FP16-to-INT8 ONNX regression on CPU.

The data comes from scikit-learn's bundled copy of the UCI handwritten-digits
dataset. Nothing is downloaded and no generated labels are used.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper
from onnxruntime.quantization import (
    CalibrationDataReader,
    CalibrationMethod,
    QuantFormat,
    QuantType,
    quantize_static,
)
from onnxruntime.quantization.shape_inference import quant_pre_process
from sklearn.datasets import load_digits
from sklearn.model_selection import train_test_split

from m2riv.adapters import OnnxRuntimeAdapter
from m2riv.artifacts import compare_artifacts, compare_onnx_numerics, inspect_artifact
from m2riv.bisect import BisectMode, bisect_regression
from m2riv.core.models import EvalCase, EvidenceRef, ModelFamily, RuntimeProfile
from m2riv.engine import ObservationCache
from m2riv.gate import GatePolicy, GateRule
from m2riv.pipeline import ReleaseComparison, compare_exact_match
from m2riv.reports import write_report_bundle

SEED = 23
RARE_DIGIT = 1
RARE_RISK_SLICE = "rare-high-ink"
RARE_RISK_THRESHOLD = 18.0
RARE_METRIC = f"accuracy@risk={RARE_RISK_SLICE}"
FIXTURE_PATH = Path(__file__).with_name("assets") / "digits-mlp-fp32.onnx.b64"
FIXTURE_SHA256 = "1d6652110add0355b2c6f4e2ab5aee63be1690384d41c79dc6eff201afd3bdb7"


class ArrayCalibrationReader(CalibrationDataReader):
    def __init__(self, rows: np.ndarray) -> None:
        self._rows = iter({"input": row[None, :].astype(np.float32, copy=False)} for row in rows)

    def get_next(self) -> dict[str, np.ndarray] | None:
        return next(self._rows, None)


def _make_onnx_model(
    weights: dict[str, np.ndarray[Any, Any]],
    *,
    numpy_dtype: np.dtype[Any],
    tensor_type: int,
) -> onnx.ModelProto:
    initializers = [
        numpy_helper.from_array(weights["w0"].astype(numpy_dtype), "w0"),
        numpy_helper.from_array(weights["b0"].astype(numpy_dtype), "b0"),
        numpy_helper.from_array(weights["w1"].astype(numpy_dtype), "w1"),
        numpy_helper.from_array(weights["b1"].astype(numpy_dtype), "b1"),
    ]
    nodes = [
        helper.make_node("MatMul", ["input", "w0"], ["hidden_linear"]),
        helper.make_node("Add", ["hidden_linear", "b0"], ["hidden_bias"]),
        helper.make_node("Relu", ["hidden_bias"], ["hidden"]),
        helper.make_node("MatMul", ["hidden", "w1"], ["output_linear"]),
        helper.make_node("Add", ["output_linear", "b1"], ["logits"]),
        helper.make_node("ArgMax", ["logits"], ["label"], axis=1, keepdims=0),
    ]
    graph = helper.make_graph(
        nodes,
        "digits_mlp",
        [helper.make_tensor_value_info("input", tensor_type, [None, 64])],
        [helper.make_tensor_value_info("label", TensorProto.INT64, [None])],
        initializers,
    )
    result = helper.make_model(
        graph,
        opset_imports=[helper.make_opsetid("", 17)],
        producer_name="m2riv-onnx-demo",
    )
    result.ir_version = 9
    result.metadata_props.add(key="dataset", value="sklearn.datasets.load_digits")
    result.metadata_props.add(key="training_seed", value=str(SEED))
    onnx.checker.check_model(result)
    return result


def _load_source_fixture() -> tuple[bytes, dict[str, np.ndarray[Any, Any]]]:
    encoded = "".join(FIXTURE_PATH.read_text("ascii").split())
    payload = base64.b64decode(encoded, validate=True)
    actual_hash = hashlib.sha256(payload).hexdigest()
    if actual_hash != FIXTURE_SHA256:
        raise RuntimeError(
            f"ONNX source fixture hash changed: expected {FIXTURE_SHA256}, got {actual_hash}"
        )
    model = onnx.load_model_from_string(payload)
    onnx.checker.check_model(model)
    weights = {
        initializer.name: numpy_helper.to_array(initializer)
        for initializer in model.graph.initializer
    }
    if set(weights) != {"w0", "b0", "w1", "b1"}:
        raise RuntimeError("ONNX source fixture has an unexpected initializer contract")
    return payload, weights


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def _metric(comparison: ReleaseComparison, metric_id: str) -> tuple[float, float, float]:
    metric = next(item for item in comparison.report.metrics if item.metric_id == metric_id)
    return metric.baseline_value, metric.candidate_value, metric.delta


def run_demo(destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    artifact_dir = destination / "artifacts"
    report_dir = destination / "reports"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    digits = load_digits()
    features = digits.data.astype(np.float32) / 16.0
    labels = digits.target.astype(np.int64)
    train_x, test_x, train_y, test_y = train_test_split(
        features,
        labels,
        test_size=0.35,
        random_state=SEED,
        stratify=labels,
    )

    rare_indices = np.flatnonzero(train_y == RARE_DIGIT)
    retained_rare_count = len(rare_indices) // 4
    source_payload, source_weights = _load_source_fixture()

    fp32_path = artifact_dir / "digits-fp32-source.onnx"
    preprocessed_path = artifact_dir / "digits-fp32-preprocessed.onnx"
    fp16_path = artifact_dir / "build-00-fp16.onnx"
    fp32_path.write_bytes(source_payload)
    # This fixed-shape MLP needs ONNX shape inference and graph optimization,
    # not transformer-oriented symbolic inference (which would add SymPy).
    quant_pre_process(fp32_path, preprocessed_path, skip_symbolic_shape=True)
    onnx.save_model(
        _make_onnx_model(
            source_weights,
            numpy_dtype=np.dtype(np.float16),
            tensor_type=TensorProto.FLOAT16,
        ),
        fp16_path,
    )

    builds: list[tuple[str, Path]] = [("build-00-fp16", fp16_path)]
    calibration_builds = (
        ("build-01-int8-balanced", 1.0),
        ("build-02-int8-calibration-scale-065", 0.65),
        ("build-03-int8-calibration-scale-060", 0.60),
    )
    for name, scale in calibration_builds:
        target = artifact_dir / f"{name}.onnx"
        quantize_static(
            preprocessed_path,
            target,
            ArrayCalibrationReader(train_x[:128] * scale),
            quant_format=QuantFormat.QDQ,
            activation_type=QuantType.QInt8,
            weight_type=QuantType.QInt8,
            calibrate_method=CalibrationMethod.MinMax,
            per_channel=False,
        )
        builds.append((name, target))

    cases = tuple(
        EvalCase(
            case_id=f"digits-test-{index:04d}",
            input=row.tolist(),
            expected=int(expected),
            slices={
                "frequency": "rare" if expected == RARE_DIGIT else "common",
                "class": str(int(expected)),
                "risk": (
                    RARE_RISK_SLICE
                    if expected == RARE_DIGIT and float(row.sum()) >= RARE_RISK_THRESHOLD
                    else "common"
                ),
            },
        )
        for index, (row, expected) in enumerate(zip(test_x, test_y, strict=True))
    )
    _write_jsonl(
        destination / "suite.jsonl",
        [case.model_dump(mode="json") for case in cases],
    )
    policy = GatePolicy(
        policy_id="onnx-quantization-release",
        rules=(
            GateRule(
                rule_id="overall-quality",
                metric="accuracy",
                margin=0.03,
                min_pairs=600,
            ),
            GateRule(
                rule_id="rare-class-quality",
                metric=RARE_METRIC,
                margin=0.015,
                min_pairs=40,
            ),
        ),
    )
    (destination / "policy.yaml").write_text(
        """schema_version: 1.0.0
policy_id: onnx-quantization-release
rules:
  - rule_id: overall-quality
    metric: accuracy
    margin: 0.03
    min_pairs: 600
  - rule_id: rare-class-quality
    metric: accuracy@risk=rare-high-ink
    margin: 0.015
    min_pairs: 40
""",
        encoding="utf-8",
    )

    baseline_adapter = OnnxRuntimeAdapter(fp16_path, model_family=ModelFamily.CV)
    baseline_profile = inspect_artifact(fp16_path)
    numerical_cases = tuple(
        [case for case in cases if case.slices.get("risk") == RARE_RISK_SLICE]
        + [case for case in cases if case.slices.get("risk") != RARE_RISK_SLICE][:81]
    )
    comparisons: list[tuple[str, ReleaseComparison]] = []
    checkpoint_rows: list[dict[str, str]] = []
    artifact_checkpoint_rows: list[dict[str, str]] = []
    regression_numerical_tensor: str | None = None
    regression_numerical_rows: tuple[Any, ...] = ()
    for name, path in builds:
        candidate_adapter = OnnxRuntimeAdapter(path, model_family=ModelFamily.CV)
        artifact_diff = compare_artifacts(baseline_profile, inspect_artifact(path))
        numerical_diff = (
            compare_onnx_numerics(
                fp16_path,
                path,
                numerical_cases,
                absolute_tolerance=1e-3,
                relative_tolerance=1e-2,
            )
            if name == "build-02-int8-calibration-scale-065"
            else None
        )
        linked_evidence = [
            EvidenceRef(
                id=artifact_diff.id,
                kind="artifact-diff",
                uri="artifact-diff.json",
            )
        ]
        if numerical_diff is not None:
            regression_numerical_tensor = numerical_diff.first_divergent_tensor
            regression_numerical_rows = tuple(
                item for item in numerical_diff.tensors if item.name != "label"
            )
            linked_evidence.append(
                EvidenceRef(
                    id=numerical_diff.id,
                    kind="numerical-diff",
                    uri="numerical-diff.json",
                )
            )
        comparison = compare_exact_match(
            baseline=baseline_adapter,
            candidate=candidate_adapter,
            cases=cases,
            policy=policy,
            cache=ObservationCache(destination / ".cache"),
            profile=RuntimeProfile(seed=SEED, device="cpu"),
            slice_keys=("risk",),
            baseline_adapter_fingerprint=f"baseline:{baseline_adapter.adapter_fingerprint}",
            candidate_adapter_fingerprint=f"candidate:{candidate_adapter.adapter_fingerprint}",
            additional_evidence=tuple(linked_evidence),
            resamples=4_000,
            confidence_level=0.95,
        )
        write_report_bundle(
            comparison.report,
            report_dir / name,
            release_plan=comparison.plan,
            evidence_manifest=comparison.evidence_manifest,
        )
        (report_dir / name / "artifact-diff.json").write_text(
            artifact_diff.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        if numerical_diff is not None:
            (report_dir / name / "numerical-diff.json").write_text(
                numerical_diff.model_dump_json(indent=2) + "\n",
                encoding="utf-8",
            )
        comparisons.append((name, comparison))
        checkpoint_rows.append({"checkpoint": name, "status": comparison.gate.status.value})
        artifact_checkpoint_rows.append(
            {
                "checkpoint": name,
                "artifact": path.relative_to(destination).as_posix(),
            }
        )

    _write_jsonl(destination / "checkpoints.jsonl", checkpoint_rows)
    _write_jsonl(destination / "artifact-checkpoints.jsonl", artifact_checkpoint_rows)
    bisect_result = bisect_regression(
        len(checkpoint_rows),
        lambda index: checkpoint_rows[index]["status"],
        mode=BisectMode.MONOTONIC,
    )
    bisect_payload = asdict(bisect_result)
    bisect_payload["first_failing_checkpoint"] = (
        checkpoint_rows[bisect_result.first_failing_index]["checkpoint"]
        if bisect_result.first_failing_index is not None
        else None
    )
    _write_json(destination / "bisect-result.json", bisect_payload)

    lines = [
        "# Reproducible ONNX quantization release demo",
        "",
        "Dataset: scikit-learn's bundled UCI handwritten-digits data (1,797 real samples).",
        f"Training rare-class setup: digit {RARE_DIGIT} retained "
        f"{retained_rare_count}/{len(rare_indices)} training examples in the fixed fixture.",
        f"Source fixture SHA-256: `{FIXTURE_SHA256}`; regeneration is explicit and reviewable.",
        f"Critical slice: digit {RARE_DIGIT} with normalized ink sum >= "
        f"{RARE_RISK_THRESHOLD:.0f}; the rule is derived from inputs, not outcomes.",
        "Baseline: CPU-executed FP16 ONNX. Candidates: CPU-executed static INT8 QDQ ONNX.",
        "Runtime: "
        f"{baseline_adapter.describe().runtime_profile.framework} "
        f"{baseline_adapter.describe().runtime_profile.framework_version}; "
        f"{baseline_adapter.describe().runtime_profile.operating_system}/"
        f"{baseline_adapter.describe().runtime_profile.architecture}; Python "
        f"{baseline_adapter.describe().runtime_profile.python_version}.",
        "",
        "| Build | Overall accuracy | Delta | Rare-class accuracy | Delta | Gate |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for name, comparison in comparisons:
        _, overall, overall_delta = _metric(comparison, "accuracy")
        _, rare, rare_delta = _metric(comparison, RARE_METRIC)
        lines.append(
            f"| {name} | {overall:.2%} | {overall_delta:+.2%} | "
            f"{rare:.2%} | {rare_delta:+.2%} | {comparison.gate.status.value.upper()} |"
        )
    first_bad = bisect_payload["first_failing_checkpoint"]
    if first_bad is None:
        interval = bisect_payload["confirmed_interval"]
        localization = (
            "Localization: inconclusive because build 02 is WARN; the confirmed "
            f"PASS/BLOCK interval is build {interval['lower_pass_index']} through "
            f"build {interval['upper_block_index']}."
        )
    else:
        localization = f"First conclusive bad build: `{first_bad}`."
    lines.extend(
        (
            "",
            localization,
            "Build-02 first shared activation outside tolerance: "
            f"`{regression_numerical_tensor}`.",
            "",
            "| Shared tensor | max abs error | RMSE | cosine similarity |",
            "|---|---:|---:|---:|",
        )
    )
    lines.extend(
        f"| `{item.name}` | {item.max_abs_error:.4f} | {item.rmse:.4f} | "
        f"{item.cosine_similarity:.6f} |"
        for item in regression_numerical_rows
    )
    lines.extend(
        (
            "",
            "The result is a paired release decision over a fixed holdout set, not a claim "
            "about all handwritten-digit distributions or all quantization methods.",
        )
    )
    summary = destination / "README.md"
    summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("runs/onnx-quantization"),
        help="Destination for models, reports, and bisect evidence.",
    )
    arguments = parser.parse_args()
    summary = run_demo(arguments.output)
    print(f"Demo complete: {summary}")


if __name__ == "__main__":
    main()
