"""Generate a complete MCR bundle without importing the reference implementation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1] / "mcr_conformance" / "full"


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def fingerprint(value: Any, namespace: str) -> str:
    domain = f"m2riv:{namespace}:v1".encode()
    return hashlib.sha256(domain + b"\0" + canonical_json(value)).hexdigest()


def identified(
    value: dict[str, Any], namespace: str, *, exclude_schema: bool = False
) -> dict[str, Any]:
    excluded = {"id"}
    if exclude_schema:
        excluded.add("schema_version")
    payload = {key: item for key, item in value.items() if key not in excluded}
    return value | {"id": f"m2riv:sha256:{fingerprint(payload, namespace)}"}


def content_id(label: str) -> str:
    return f"m2riv:sha256:{fingerprint(label, 'independent-fixture')}"


def evidence_ref(identifier: str, kind: str, uri: str | None = None) -> dict[str, Any]:
    return {
        "id": identifier,
        "kind": kind,
        "media_type": "application/json",
        "uri": uri,
        "redacted": False,
    }


def build_bundle() -> dict[str, dict[str, Any]]:
    observations = [
        evidence_ref(content_id("observation-1"), "observation"),
        evidence_ref(content_id("observation-2"), "observation"),
    ]
    evidence_set = {
        "id": "",
        "count": 2,
        "members": [item["id"] for item in observations],
    }
    evidence_set["id"] = "m2riv:sha256:" + fingerprint(
        {"members": evidence_set["members"]}, "evidence-set"
    )
    manifest_payload = {
        "schema_version": "1.0.0",
        "evidence": observations,
        "sets": [evidence_set],
    }
    manifest = {
        "schema_version": "1.0.0",
        "id": "m2riv:sha256:" + fingerprint(manifest_payload, "evidence-manifest"),
        "evidence": observations,
        "sets": [evidence_set],
    }
    manifest_ref = {
        "id": manifest["id"],
        "uri": "evidence-manifest.json",
        "media_type": "application/vnd.m2riv.evidence-manifest+json",
        "evidence_count": 2,
        "set_count": 1,
    }

    plan = identified(
        {
            "schema_version": "1.0.0",
            "id": "",
            "policy_id": "independent-policy",
            "policy_fingerprint": "1" * 64,
            "suite_fingerprint": "2" * 64,
            "runtime_profile_fingerprint": "3" * 64,
            "seed": 17,
            "resamples": 200,
            "confidence_level": 0.95,
            "slice_keys": [],
            "metrics": [
                {
                    "metric_id": "accuracy",
                    "base_metric_id": "accuracy",
                    "scope": "overall",
                    "direction": "higher_is_better",
                    "unit": "fraction",
                    "binary": True,
                    "plugin_name": None,
                    "plugin_version": None,
                }
            ],
            "bindings": [
                {
                    "rule_id": "accuracy-floor",
                    "metric_id": "accuracy",
                    "base_metric_id": "accuracy",
                }
            ],
            "plugins": [],
        },
        "release-plan",
    )

    artifact_diff = identified(
        {
            "schema_version": "1.0.0",
            "id": "",
            "baseline_profile_id": content_id("artifact-baseline"),
            "candidate_profile_id": content_id("artifact-candidate"),
            "artifact_changed": True,
            "format_changed": False,
            "size_delta_bytes": -128,
            "file_count_delta": 0,
            "changed_components": ["model.onnx"],
            "opset_changes": [],
            "operator_changes": [],
            "initializer_dtype_changes": [],
            "node_count_delta": 0,
            "initializer_count_delta": 0,
            "parameter_count_delta": 0,
            "inputs_changed": False,
            "outputs_changed": False,
            "external_data_changed": False,
            "quantization_format_changed": True,
        },
        "artifact-diff",
        exclude_schema=True,
    )
    numerical_diff = identified(
        {
            "schema_version": "1.0.0",
            "id": "",
            "baseline_profile_id": artifact_diff["baseline_profile_id"],
            "candidate_profile_id": artifact_diff["candidate_profile_id"],
            "case_count": 2,
            "absolute_tolerance": 0.001,
            "relative_tolerance": 0.001,
            "baseline_only_tensors": [],
            "candidate_only_tensors": [],
            "tensors": [
                {
                    "name": "logits",
                    "baseline_dtype": "float32",
                    "candidate_dtype": "float32",
                    "shape": [2, 2],
                    "element_count": 4,
                    "max_abs_error": 0.02,
                    "mean_abs_error": 0.005,
                    "rmse": 0.01,
                    "max_relative_error": 0.03,
                    "cosine_similarity": 0.999,
                    "within_tolerance": False,
                }
            ],
            "first_divergent_tensor": "logits",
        },
        "onnx-numerical-diff",
        exclude_schema=True,
    )
    supplemental = [
        evidence_ref(artifact_diff["id"], "artifact-diff", "artifact-diff.json"),
        evidence_ref(numerical_diff["id"], "numerical-diff", "numerical-diff.json"),
    ]

    runtime_profile = {
        "seed": 17,
        "deterministic": True,
        "repetitions": 1,
        "framework": "independent-runtime",
        "framework_version": "1.0",
        "device": "cpu",
        "dtype": "float32",
        "operating_system": "portable-fixture",
        "architecture": "generic",
        "python_version": "3.11+",
        "parameters": {},
    }
    execution = {
        "role": "candidate",
        "executor_id": "example.independent-producer",
        "executor_version": "1.0",
        "config_fingerprint": "4" * 64,
        "runtime_profile": runtime_profile,
        "capabilities": ["paired-observations"],
        "requested_cases": 2,
        "returned_observations": 2,
        "cache_hits": 0,
    }
    metric = {
        "metric_id": "accuracy",
        "scope": "overall",
        "unit": "score",
        "direction": "higher_is_better",
        "baseline_value": 1.0,
        "candidate_value": 0.5,
        "delta": -0.5,
        "confidence_level": None,
        "interval_lower": None,
        "interval_upper": None,
        "effect_size": None,
        "sample_size": 2,
        "evidence_set_id": evidence_set["id"],
        "identity_scope": "evidence",
    }
    finding = {
        "rule_id": "accuracy-floor",
        "status": "BLOCK",
        "message": "independent fixture crosses the declared accuracy floor",
        "metric_id": "accuracy",
        "evidence": [],
        "evidence_set_id": evidence_set["id"],
    }
    decision = {"status": "BLOCK", "allowed": False, "findings": [finding]}
    created_at = "2026-08-29T00:00:00+00:00"
    baseline_id = content_id("baseline-snapshot")
    candidate_id = content_id("candidate-snapshot")
    evidence_payload = {
        "schema_version": "1.3.0",
        "baseline_snapshot_id": baseline_id,
        "candidate_snapshot_id": candidate_id,
        "release_plan_id": plan["id"],
        "metrics": [metric],
        "finding_evidence": [
            {
                "rule_id": finding["rule_id"],
                "metric_id": finding["metric_id"],
                "evidence_set_id": finding["evidence_set_id"],
                "evidence": finding["evidence"],
            }
        ],
        "evidence_manifest": manifest_ref,
        "evidence": supplemental,
    }
    report_id = "m2riv:sha256:" + fingerprint(
        evidence_payload, "model-change-evidence"
    )
    run_payload = {
        "schema_version": "1.3.0",
        "evidence_id": report_id,
        "created_at": created_at,
        "baseline_snapshot_id": baseline_id,
        "candidate_snapshot_id": candidate_id,
        "release_plan_id": plan["id"],
        "executions": [execution],
        "metrics": [metric],
        "decision": decision,
        "evidence_manifest": manifest_ref,
        "evidence": supplemental,
        "limitations": ["Conformance evidence only; no model was executed."],
    }
    report = {
        "schema_version": "1.3.0",
        "id": report_id,
        "run_id": "m2riv:sha256:" + fingerprint(run_payload, "model-change-run"),
        "created_at": created_at,
        "baseline_snapshot_id": baseline_id,
        "candidate_snapshot_id": candidate_id,
        "release_plan_id": plan["id"],
        "executions": [execution],
        "metrics": [metric],
        "decision": decision,
        "evidence_manifest": manifest_ref,
        "evidence": supplemental,
        "limitations": ["Conformance evidence only; no model was executed."],
    }
    return {
        "m2riv-report.json": report,
        "evidence-manifest.json": manifest,
        "release-plan.json": plan,
        "artifact-diff.json": artifact_diff,
        "numerical-diff.json": numerical_diff,
    }


def render(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    changed: list[str] = []
    for name, payload in build_bundle().items():
        destination = ROOT / name
        expected = render(payload)
        if destination.exists() and destination.read_text(encoding="utf-8") == expected:
            continue
        changed.append(name)
        if not arguments.check:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(expected, encoding="utf-8", newline="\n")
    if arguments.check and changed:
        parser.error(f"stale independent-producer fixture files: {', '.join(changed)}")


if __name__ == "__main__":
    main()
