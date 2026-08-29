"""Build and gate a real FP16-to-INT8 ONNX regression on CPU.

The data comes from scikit-learn's bundled copy of the UCI handwritten-digits
dataset. Nothing is downloaded and no generated labels are used.
"""

from __future__ import annotations

import argparse
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
from sklearn.neural_network import MLPClassifier

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


class ArrayCalibrationReader(CalibrationDataReader):
    def __init__(self, rows: np.ndarray) -> None:
        self._rows = iter(
            {"input": row[None, :].astype(np.float32, copy=False)} for row in rows
        )

    def get_next(self) -> dict[str, np.ndarray] | None:
        return next(self._rows, None)


def _make_onnx_model(
    model: MLPClassifier,
    *,
    numpy_dtype: np.dtype[Any],
    tensor_type: int,
) -> onnx.ModelProto:
    initializers = [
        numpy_helper.from_array(model.coefs_[0].astype(numpy_dtype), "w0"),
        numpy_helper.from_array(model.intercepts_[0].astype(numpy_dtype), "b0"),
        numpy_helper.from_array(model.coefs_[1].astype(numpy_dtype), "w1"),
        numpy_helper.from_array(model.intercepts_[1].astype(numpy_dtype), "b1"),
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
    common_indices = np.flatnonzero(train_y != RARE_DIGIT)
    retained_rare = rare_indices[: len(rare_indices) // 4]
    retained = np.concatenate((common_indices, retained_rare))
    np.random.default_rng(SEED).shuffle(retained)
    classifier = MLPClassifier(
        hidden_layer_sizes=(32,),
        activation="relu",
        solver="lbfgs",
        alpha=1e-4,
        max_iter=500,
        random_state=SEED,
    )
    classifier.fit(train_x[retained], train_y[retained])

    fp32_path = artifact_dir / "digits-fp32-source.onnx"
    preprocessed_path = artifact_dir / "digits-fp32-preprocessed.onnx"
    fp16_path = artifact_dir / "build-00-fp16.onnx"
    onnx.save_model(
        _make_onnx_model(
            classifier,
            numpy_dtype=np.dtype(np.float32),
            tensor_type=TensorProto.FLOAT,
        ),
        fp32_path,
    )
    # This fixed-shape MLP needs ONNX shape inference and graph optimization,
    # not transformer-oriented symbolic inference (which would add SymPy).
    quant_pre_process(fp32_path, preprocessed_path, skip_symbolic_shape=True)
    onnx.save_model(
        _make_onnx_model(
            classifier,
            numpy_dtype=np.dtype(np.float16),
            tensor_type=TensorProto.FLOAT16,
        ),
        fp16_path,
    )

    builds: list[tuple[str, Path]] = [("build-00-fp16", fp16_path)]
    calibration_builds = (
        ("build-01-int8-balanced", 1.0),
        ("build-02-int8-calibration-scale-075", 0.75),
        ("build-03-int8-calibration-scale-070", 0.70),
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
    first_bad_numerical_tensor: str | None = None
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
            if name == "build-02-int8-calibration-scale-075"
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
            first_bad_numerical_tensor = numerical_diff.first_divergent_tensor
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
        checkpoint_rows.append(
            {"checkpoint": name, "status": comparison.gate.status.value}
        )
        artifact_checkpoint_rows.append(
            {
                "checkpoint": name,
                "artifact": path.relative_to(destination).as_posix(),
            }
        )

    _write_jsonl(destination / "checkpoints.jsonl", checkpoint_rows)
    _write_jsonl(
        destination / "artifact-checkpoints.jsonl", artifact_checkpoint_rows
    )
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
        f"{len(retained_rare)}/{len(rare_indices)} training examples.",
        f"Critical slice: digit {RARE_DIGIT} with normalized ink sum >= "
        f"{RARE_RISK_THRESHOLD:.0f}; the rule is derived from inputs, not outcomes.",
        "Baseline: CPU-executed FP16 ONNX. Candidates: CPU-executed static INT8 QDQ ONNX.",
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
    lines.extend(
        (
            "",
            f"First bad build: `{first_bad}`.",
            f"First shared activation outside tolerance: `{first_bad_numerical_tensor}`.",
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
