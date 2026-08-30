from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

from typer.testing import CliRunner

from m2riv.cli import app
from m2riv.conformance import verify_consumer_conformance

runner = CliRunner()


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_polygraphy_reference_producer_translates_normalized_results(tmp_path: Path) -> None:
    module = _load_module("polygraphy_mcr_producer", Path("integrations/polygraphy_mcr/produce.py"))
    payload = module._load_normalized(Path("integrations/polygraphy_mcr/normalized-results.json"))
    baseline, candidate, suite = module.produce_inputs(payload, tmp_path)

    assert len(baseline.read_text(encoding="utf-8").splitlines()) == 10
    candidate_rows = [json.loads(line) for line in candidate.read_text().splitlines()]
    assert sum(row["output"] == "mismatch" for row in candidate_rows) == 1
    assert len(suite.read_text(encoding="utf-8").splitlines()) == 10


def test_polygraphy_first_mile_cli_imports_normalized_evidence(tmp_path: Path) -> None:
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        """schema_version: 1.0.0
policy_id: importer-smoke
rules:
  - rule_id: parity
    metric: accuracy
    margin: 1.0
    min_pairs: 10
""",
        encoding="utf-8",
    )
    output = tmp_path / "imported"
    result = runner.invoke(
        app,
        [
            "import",
            "polygraphy",
            "integrations/polygraphy_mcr/normalized-results.json",
            "--format",
            "normalized",
            "--policy",
            str(policy),
            "--output",
            str(output),
            "--resamples",
            "100",
        ],
    )

    assert result.exit_code == 0, result.stderr
    assert "SOURCE TRUST: normalized interchange" in result.stdout
    assert "EVALUATION DECISION: PASS" in result.stdout
    assert (output / "mcr-report.json").is_file()
    assert (output / "translated" / "candidate.jsonl").is_file()


def test_mlflow_consumer_emits_a_conformant_receipt(tmp_path: Path) -> None:
    receipt = tmp_path / "receipt.json"
    completed = subprocess.run(
        [
            sys.executable,
            "integrations/mlflow_mcr/consume.py",
            "--emit-conformance-receipt",
            "examples/mcr_conformance",
            str(receipt),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    result = verify_consumer_conformance(receipt, fixtures="examples/mcr_conformance")
    assert result.conformant
    assert result.implementation_name == "m2riv.mlflow-consumer"
