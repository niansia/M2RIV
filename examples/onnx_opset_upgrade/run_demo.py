"""Verify a CPU-only ONNX opset upgrade with structural and numerical evidence."""

from __future__ import annotations

import argparse
from pathlib import Path

import onnx
from onnx import TensorProto, helper

from merriv.adapters import OnnxRuntimeAdapter
from merriv.artifacts import compare_artifacts, compare_onnx_numerics, inspect_artifact
from merriv.core.models import EvalCase, EvidenceRef, ModelFamily, RuntimeProfile
from merriv.engine import ObservationCache
from merriv.gate import GatePolicy, GateRule
from merriv.pipeline import compare_exact_match
from merriv.reports import write_report_bundle


def _baseline_model() -> onnx.ModelProto:
    graph = helper.make_graph(
        [helper.make_node("Relu", ["input"], ["output"], name="activation")],
        "opset-upgrade",
        [helper.make_tensor_value_info("input", TensorProto.FLOAT, [None, 4])],
        [helper.make_tensor_value_info("output", TensorProto.FLOAT, [None, 4])],
    )
    model = helper.make_model(
        graph,
        opset_imports=[helper.make_opsetid("", 17)],
        producer_name="merriv-opset-demo",
    )
    model.ir_version = 9
    onnx.checker.check_model(model)
    return model


def run(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    artifacts = destination / "artifacts"
    report_directory = destination / "report"
    artifacts.mkdir(exist_ok=True)
    baseline_path = artifacts / "relu-opset17.onnx"
    candidate_path = artifacts / "relu-opset18.onnx"
    onnx.save_model(_baseline_model(), baseline_path)
    onnx.save_model(
        onnx.version_converter.convert_version(_baseline_model(), 18),
        candidate_path,
    )
    rows = (
        [-2.0, -1.0, 0.0, 1.0],
        [4.0, -3.0, 2.0, -1.0],
        [0.25, 0.5, 0.75, 1.0],
        [-0.25, -0.5, -0.75, -1.0],
    )
    cases = tuple(
        EvalCase(
            case_id=f"opset-{index}",
            input=row,
            expected=[max(value, 0.0) for value in row],
        )
        for index, row in enumerate(rows)
    )
    artifact_diff = compare_artifacts(
        inspect_artifact(baseline_path), inspect_artifact(candidate_path)
    )
    numerical_diff = compare_onnx_numerics(
        baseline_path,
        candidate_path,
        cases,
        absolute_tolerance=0.0,
        relative_tolerance=0.0,
    )
    baseline_adapter = OnnxRuntimeAdapter(baseline_path, model_family=ModelFamily.CUSTOM)
    candidate_adapter = OnnxRuntimeAdapter(candidate_path, model_family=ModelFamily.CUSTOM)
    comparison = compare_exact_match(
        baseline=baseline_adapter,
        candidate=candidate_adapter,
        cases=cases,
        policy=GatePolicy(
            policy_id="opset-upgrade",
            rules=(
                GateRule(
                    rule_id="behavior-preserved",
                    metric="accuracy",
                    margin=0.0,
                    min_pairs=len(cases),
                ),
            ),
        ),
        cache=ObservationCache(destination / ".cache"),
        profile=RuntimeProfile(seed=0, device="cpu"),
        baseline_adapter_fingerprint=f"baseline:{baseline_adapter.adapter_fingerprint}",
        candidate_adapter_fingerprint=f"candidate:{candidate_adapter.adapter_fingerprint}",
        additional_evidence=(
            EvidenceRef(id=artifact_diff.id, kind="artifact-diff", uri="artifact-diff.json"),
            EvidenceRef(
                id=numerical_diff.id,
                kind="numerical-diff",
                uri="numerical-diff.json",
            ),
        ),
        resamples=500,
    )
    write_report_bundle(
        comparison.report,
        report_directory,
        release_plan=comparison.plan,
        evidence_manifest=comparison.evidence_manifest,
    )
    (report_directory / "artifact-diff.json").write_text(
        artifact_diff.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    (report_directory / "numerical-diff.json").write_text(
        numerical_diff.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"{comparison.report.decision.status.value}: opset 17 -> 18; "
        f"first numerical divergence = {numerical_diff.first_divergent_tensor}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("runs/onnx-opset-upgrade"))
    arguments = parser.parse_args()
    run(arguments.output)


if __name__ == "__main__":
    main()
