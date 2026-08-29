from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from m2riv.bisect import load_checkpoint_artifacts
from m2riv.cli import app
from m2riv.io import InputFormatError

runner = CliRunner()


def _write_execution_fixture(root: Path) -> tuple[Path, Path, Path]:
    suite = root / "suite.jsonl"
    policy = root / "policy.yaml"
    manifest = root / "artifacts.jsonl"
    cases = []
    for index in range(6):
        cases.append(
            {
                "case_id": f"case-{index}",
                "input": {"index": index},
                "expected": f"label-{index}",
                "slices": {"frequency": "rare" if index >= 4 else "common"},
            }
        )
    suite.write_text(
        "".join(json.dumps(case) + "\n" for case in cases), encoding="utf-8"
    )
    policy.write_text(
        """schema_version: 1.0.0
policy_id: executed-bisect
rules:
  - rule_id: overall-quality
    metric: accuracy
    margin: 1.0
    min_pairs: 6
  - rule_id: rare-quality
    metric: accuracy@frequency=rare
    margin: 0.1
    min_pairs: 2
""",
        encoding="utf-8",
    )
    manifest_rows = []
    for checkpoint_index in range(4):
        artifact = root / f"checkpoint-{checkpoint_index}.jsonl"
        observations = [
            {
                "case_id": case["case_id"],
                "output": (
                    "wrong"
                    if checkpoint_index >= 2 and case["slices"]["frequency"] == "rare"
                    else case["expected"]
                ),
                "latency_ms": float(checkpoint_index + 1),
            }
            for case in cases
        ]
        artifact.write_text(
            "".join(json.dumps(item) + "\n" for item in observations),
            encoding="utf-8",
        )
        manifest_rows.append(
            {"checkpoint": f"checkpoint-{checkpoint_index}", "artifact": artifact.name}
        )
    manifest.write_text(
        "".join(json.dumps(item) + "\n" for item in manifest_rows),
        encoding="utf-8",
    )
    return manifest, suite, policy


def test_bisect_run_executes_selected_artifacts_and_finds_boundary(tmp_path: Path) -> None:
    manifest, suite, policy = _write_execution_fixture(tmp_path)
    output = tmp_path / "run"

    result = runner.invoke(
        app,
        [
            "bisect-run",
            str(manifest),
            "--suite",
            str(suite),
            "--policy",
            str(policy),
            "--slice-key",
            "frequency",
            "--output",
            str(output),
            "--resamples",
            "100",
        ],
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["outcome"] == "first_failing"
    assert payload["first_failing_index"] == 2
    assert payload["first_failing_checkpoint"] == "checkpoint-2"
    assert [item["index"] for item in payload["executed_checkpoints"]] == [0, 1, 2, 3]
    assert json.loads((output / "bisect-result.json").read_text("utf-8")) == payload

    blocking_directory = output / "checkpoints" / "000002"
    report = json.loads((blocking_directory / "m2riv-report.json").read_text("utf-8"))
    evidence_manifest = json.loads(
        (blocking_directory / "evidence-manifest.json").read_text("utf-8")
    )
    assert report["decision"]["status"] == "BLOCK"
    assert all("evidence" not in metric for metric in report["metrics"])
    assert all(metric["evidence_set_id"] for metric in report["metrics"])
    assert len(evidence_manifest["sets"]) < len(report["metrics"])
    assert (blocking_directory / "m2riv-report.json").stat().st_size < 30_000


def test_artifact_manifest_rejects_commands_and_missing_paths(tmp_path: Path) -> None:
    manifest = tmp_path / "hostile.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "checkpoint": "checkpoint-0",
                "artifact": "missing.jsonl",
                "command": "echo should-never-run",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(InputFormatError, match="only checkpoint and artifact"):
        load_checkpoint_artifacts(manifest)

    manifest.write_text(
        json.dumps({"checkpoint": "checkpoint-0", "artifact": "missing.jsonl"}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(InputFormatError, match="does not exist"):
        load_checkpoint_artifacts(manifest)
