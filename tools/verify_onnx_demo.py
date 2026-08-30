"""Verify the generated ONNX demo from machine-readable evidence, not prose."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from merriv.reports import verify_report_bundle

EXPECTED_STATUSES = {
    # The FP16 self-comparison is retained as auditable reference evidence even
    # though the generated presentation labels it REFERENCE rather than PASS.
    "build-00-fp16": frozenset({"PASS"}),
    "build-01-int8-balanced": frozenset({"PASS"}),
    "build-02-int8-calibration-scale-055": frozenset({"BLOCK"}),
    "build-03-int8-calibration-scale-050": frozenset({"BLOCK"}),
}
EXPECTED_ACCURACY_RANGES = {
    "build-00-fp16": ((596 / 629, 596 / 629), (369 / 386, 369 / 386)),
    "build-01-int8-balanced": ((596 / 629, 597 / 629), (368 / 386, 369 / 386)),
    # ONNX Runtime's CPU kernels differ by a few predictions across the
    # hosted Linux and Windows runners. The gate verdict remains BLOCK on
    # both; this range records the observed cross-platform accuracy envelope.
    "build-02-int8-calibration-scale-055": ((568 / 629, 574 / 629), (344 / 386, 348 / 386)),
    "build-03-int8-calibration-scale-050": ((565 / 629, 570 / 629), (343 / 386, 348 / 386)),
}
CALIBRATION_REGRESSION_BUILD = "build-02-int8-calibration-scale-055"
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

    for checkpoint, allowed_statuses in EXPECTED_STATUSES.items():
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
        status = report.get("decision", {}).get("status")
        if status not in allowed_statuses:
            raise ValueError(
                f"{checkpoint} has status {status!r}; expected one of {sorted(allowed_statuses)}"
            )
        policy_satisfied = report.get("decision", {}).get("allowed")
        if policy_satisfied is not (status == "PASS"):
            raise ValueError(f"{checkpoint} has inconsistent evaluation-policy semantics")
        findings = report.get("decision", {}).get("findings", [])
        if not any(
            "tango-score-matched-proportions" in str(finding.get("message"))
            for finding in findings
            if isinstance(finding, dict)
        ):
            raise ValueError(f"{checkpoint} did not retain the matched-binary score method")
        if any(
            finding.get("raw_p_value") is None or finding.get("adjusted_p_value") is None
            for finding in findings
            if isinstance(finding, dict)
        ):
            raise ValueError(f"{checkpoint} omitted matched-binary score evidence")
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
        expected_overall, expected_critical = EXPECTED_ACCURACY_RANGES[checkpoint]
        for metric_id, expected_range in (
            ("accuracy", expected_overall),
            ("accuracy@risk=high-ink", expected_critical),
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
    if (
        bisect.get("outcome") != "first_failing"
        or bisect.get("first_failing_checkpoint") != CALIBRATION_REGRESSION_BUILD
        or bisect.get("first_failing_index") != 2
        or bisect.get("confirmed_interval") != {"lower_pass_index": 1, "upper_block_index": 2}
    ):
        raise ValueError("demo bisect did not locate the first contracted-calibration build")
    artifact_diff = _object(root / "reports" / CALIBRATION_REGRESSION_BUILD / "artifact-diff.json")
    if not artifact_diff.get("quantization_format_changed"):
        raise ValueError("calibration-regression build has no quantization change")
    operator_names = {item.get("name") for item in artifact_diff.get("operator_changes", [])}
    if not {
        "ai.onnx::QuantizeLinear",
        "ai.onnx::DequantizeLinear",
    }.issubset(operator_names):
        raise ValueError("calibration-regression build lacks the expected QDQ graph changes")
    numerical_diff = _object(
        root / "reports" / CALIBRATION_REGRESSION_BUILD / "numerical-diff.json"
    )
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
    onset_report = _object(root / "reports" / CALIBRATION_REGRESSION_BUILD / "mcr-report.json")
    linked_kinds = {item.get("kind") for item in onset_report.get("evidence", [])}
    if "numerical-diff" not in linked_kinds:
        raise ValueError("calibration-regression report does not link its numerical diff")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    verify(arguments.destination)
    print(f"Verified ONNX release evidence under {arguments.destination}")


if __name__ == "__main__":
    main()
