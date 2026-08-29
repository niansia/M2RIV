"""Verify the generated ONNX demo from machine-readable evidence, not prose."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from m2riv.reports import verify_report_bundle

EXPECTED_STATUSES = {
    "build-00-fp16": "PASS",
    "build-01-int8-balanced": "PASS",
    "build-02-int8-calibration-scale-065": "BLOCK",
    "build-03-int8-calibration-scale-060": "BLOCK",
}
EXPECTED_ACCURACY_RANGES = {
    "build-00-fp16": ((596 / 629, 596 / 629), (43 / 47, 43 / 47)),
    # The source weights are fixed. Bounded ranges still acknowledge that ORT's
    # platform-specific INT8 kernels can move borderline samples across argmax.
    "build-01-int8-balanced": ((595 / 629, 597 / 629), (42 / 47, 44 / 47)),
    "build-02-int8-calibration-scale-065": ((584 / 629, 586 / 629), (35 / 47, 37 / 47)),
    "build-03-int8-calibration-scale-060": ((581 / 629, 584 / 629), (33 / 47, 36 / 47)),
}
FIRST_BAD = "build-02-int8-calibration-scale-065"
MAX_MCR_BYTES = 32 * 1024
ACCURACY_TOLERANCE = 1e-12


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def verify(destination: Path) -> None:
    root = destination.resolve()
    artifact_rows = [
        json.loads(line)
        for line in (root / "artifact-checkpoints.jsonl").read_text("utf-8").splitlines()
        if line.strip()
    ]
    if [row.get("checkpoint") for row in artifact_rows] != list(EXPECTED_STATUSES):
        raise ValueError("artifact checkpoint order does not match the release sequence")
    for row in artifact_rows:
        if set(row) != {"checkpoint", "artifact"}:
            raise ValueError("artifact manifest contains fields outside the execution contract")
        artifact = (root / row["artifact"]).resolve()
        if not artifact.is_relative_to(root) or not artifact.is_file():
            raise ValueError("artifact manifest path escapes the demo or is missing")

    for checkpoint, expected_status in EXPECTED_STATUSES.items():
        report_directory = root / "reports" / checkpoint
        verification = verify_report_bundle(report_directory)
        if not verification.valid:
            raise ValueError(f"{checkpoint} MCR bundle failed integrity verification")
        report_path = report_directory / "mcr-report.json"
        if report_path.stat().st_size > MAX_MCR_BYTES:
            raise ValueError(f"{checkpoint} MCR exceeds {MAX_MCR_BYTES} bytes")
        report = _object(report_path)
        manifest = _object(report_directory / "evidence-manifest.json")
        reference = report.get("evidence_manifest")
        if report.get("schema_version") != "0.4.0":
            raise ValueError(f"{checkpoint} is not an MCR 0.4 report")
        if report.get("decision", {}).get("status") != expected_status:
            raise ValueError(f"{checkpoint} has the wrong release status")
        if not isinstance(reference, dict) or reference.get("id") != manifest.get("id"):
            raise ValueError(f"{checkpoint} evidence manifest identity is not linked")
        evidence = manifest.get("evidence", [])
        evidence_sets = manifest.get("sets", [])
        if reference.get("evidence_count") != len(evidence) or reference.get("set_count") != len(
            evidence_sets
        ):
            raise ValueError(f"{checkpoint} evidence manifest counts do not match")
        set_ids = {item.get("id") for item in evidence_sets}
        if any(
            metric.get("evidence_set_id") not in set_ids for metric in report.get("metrics", [])
        ):
            raise ValueError(f"{checkpoint} metric has a dangling evidence set")
        if any(
            finding.get("evidence_set_id") not in set_ids
            for finding in report.get("decision", {}).get("findings", [])
        ):
            raise ValueError(f"{checkpoint} finding has a dangling evidence set")
        metrics = {item.get("metric_id"): item for item in report.get("metrics", [])}
        expected_overall, expected_rare = EXPECTED_ACCURACY_RANGES[checkpoint]
        for metric_id, expected_range in (
            ("accuracy", expected_overall),
            ("accuracy@risk=rare-high-ink", expected_rare),
        ):
            actual = metrics.get(metric_id, {}).get("candidate_value")
            lower, upper = expected_range
            if (
                not isinstance(actual, (int, float))
                or actual < lower - ACCURACY_TOLERANCE
                or actual > upper + ACCURACY_TOLERANCE
            ):
                raise ValueError(
                    f"{checkpoint} {metric_id} changed: expected within "
                    f"[{lower}, {upper}], got {actual}"
                )

    bisect = _object(root / "bisect-result.json")
    if bisect.get("first_failing_checkpoint") != FIRST_BAD:
        raise ValueError("demo bisect did not locate the intended first bad build")
    artifact_diff = _object(root / "reports" / FIRST_BAD / "artifact-diff.json")
    if not artifact_diff.get("quantization_format_changed"):
        raise ValueError("first bad build has no machine-readable quantization change")
    operator_names = {item.get("name") for item in artifact_diff.get("operator_changes", [])}
    if not {
        "ai.onnx::QuantizeLinear",
        "ai.onnx::DequantizeLinear",
    }.issubset(operator_names):
        raise ValueError("first bad build does not contain the expected QDQ graph changes")
    numerical_diff = _object(root / "reports" / FIRST_BAD / "numerical-diff.json")
    tensor_rows = numerical_diff.get("tensors")
    if not isinstance(tensor_rows, list):
        raise ValueError("numerical diff does not contain per-tensor evidence")
    first_failed = next(
        (
            item.get("name")
            for item in tensor_rows
            if isinstance(item, dict) and item.get("within_tolerance") is False
        ),
        None,
    )
    declared_first = numerical_diff.get("first_divergent_tensor")
    if declared_first != first_failed or declared_first not in {
        "hidden_linear",
        "hidden_bias",
        "hidden",
    }:
        raise ValueError("numerical diff did not locate the first shared hidden activation drift")
    first_bad_report = _object(root / "reports" / FIRST_BAD / "mcr-report.json")
    linked_kinds = {item.get("kind") for item in first_bad_report.get("evidence", [])}
    if "numerical-diff" not in linked_kinds:
        raise ValueError("first bad MCR does not link its numerical diff")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    verify(arguments.destination)
    print(f"Verified ONNX release evidence under {arguments.destination}")


if __name__ == "__main__":
    main()
