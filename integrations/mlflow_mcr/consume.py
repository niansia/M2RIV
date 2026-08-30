"""Verify and log a Model Change Report bundle to MLflow without importing Merriv."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

MAX_REPORT_BYTES = 16 * 1024 * 1024


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _fingerprint(value: Any, *, namespace: str) -> str:
    digest = hashlib.sha256()
    digest.update(f"mcr:{namespace}:v1".encode())
    digest.update(b"\x00")
    digest.update(_canonical_json(value))
    return digest.hexdigest()


def _load_report(source: Path) -> dict[str, Any]:
    path = source / "mcr-report.json" if source.is_dir() else source
    if path.stat().st_size > MAX_REPORT_BYTES:
        raise ValueError("MCR report exceeds the consumer size limit")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("MCR report must be a JSON object")
    return payload


def _verify(source: Path, command: str) -> dict[str, Any]:
    # The caller explicitly selects the local verifier binary. No shell is used.
    completed = subprocess.run(  # noqa: S603
        [command, "mcr", "verify", str(source), "--strict"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise ValueError(f"MCR verification failed: {completed.stdout.strip()}")
    result = json.loads(completed.stdout)
    if not result.get("valid") or not result.get("bundle_verification_complete"):
        raise ValueError("MCR verifier did not establish complete local self-consistency")
    return result


def _log_plan(report: dict[str, Any], verification: dict[str, Any], source: Path) -> dict[str, Any]:
    tags = {
        "mcr.report_id": report["id"],
        "mcr.evidence_id": report["evidence_id"],
        "mcr.run_id": report["run_id"],
        "mcr.schema_version": report["schema_version"],
        "mcr.evaluation_status": report["decision"]["status"],
        "mcr.evaluation_policy_satisfied": str(report["decision"]["allowed"]).lower(),
        "mcr.deployment_authorization": "not-evaluated",
        "mcr.verification_scope": verification["trust_scope"],
        "mcr.authenticity_verified": str(verification["authenticity_verified"]).lower(),
        "mcr.evidence_body_coverage": str(
            verification["evidence_body_coverage"]["coverage"]
        ),
        "mcr.metric_recomputable": str(verification["metric_recomputable"]).lower(),
    }
    metrics: dict[str, float] = {}
    for metric in report.get("metrics", []):
        key = f"mcr.{metric['metric_id']}.{metric.get('scope', 'overall')}"
        metrics[f"{key}.candidate"] = float(metric["candidate_value"])
        metrics[f"{key}.delta"] = float(metric["delta"])
    artifact = source if source.is_dir() else source.parent
    return {"tags": tags, "metrics": metrics, "artifact_directory": str(artifact.resolve())}


def _emit_receipt(fixtures: Path, output: Path) -> None:
    profiles = []
    for name in ("pass", "warn", "insufficient_power", "block", "error"):
        report = _load_report(fixtures / name)
        status = report["decision"]["status"]
        profiles.append(
            {
                "profile": name,
                "report_id": report["id"],
                "evidence_id": report["evidence_id"],
                "decision_status": status,
                "evaluation_policy_satisfied": status == "PASS",
            }
        )
    payload = {
        "schema_version": "0.3.0",
        "implementation_name": "m2riv.mlflow-consumer",
        "implementation_version": "1.0.0",
        "profiles": profiles,
    }
    receipt = {
        "schema_version": payload["schema_version"],
        "id": f"mcr:sha256:{_fingerprint(payload, namespace='mcr-consumer-receipt')}",
        "implementation_name": payload["implementation_name"],
        "implementation_version": payload["implementation_version"],
        "profiles": profiles,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, nargs="?")
    parser.add_argument("--experiment", default="merriv-release-evidence")
    parser.add_argument("--run-name")
    parser.add_argument(
        "--merriv-command",
        "--m2riv-command",
        dest="merriv_command",
        default="merriv",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--emit-conformance-receipt",
        nargs=2,
        metavar=("FIXTURES", "OUTPUT"),
    )
    arguments = parser.parse_args()
    try:
        if arguments.emit_conformance_receipt:
            fixtures, output = map(Path, arguments.emit_conformance_receipt)
            _emit_receipt(fixtures, output)
            print(output)
            return
        if arguments.source is None:
            parser.error("source is required unless --emit-conformance-receipt is used")
        report = _load_report(arguments.source)
        verification = _verify(arguments.source, arguments.merriv_command)
        plan = _log_plan(report, verification, arguments.source)
        if arguments.dry_run:
            print(json.dumps(plan, indent=2, sort_keys=True))
            return
        try:
            import mlflow
        except ImportError as error:
            raise RuntimeError("MLflow is required unless --dry-run is used") from error
        mlflow.set_experiment(arguments.experiment)
        with mlflow.start_run(run_name=arguments.run_name):
            mlflow.set_tags(plan["tags"])
            mlflow.log_metrics(plan["metrics"])
            mlflow.log_artifacts(plan["artifact_directory"], artifact_path="mcr")
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError, KeyError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(3) from error


if __name__ == "__main__":
    main()
