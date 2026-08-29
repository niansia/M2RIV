import json
from pathlib import Path

from typer.testing import CliRunner

from m2riv.cli import app
from m2riv.conformance import ConformanceProfile, create_consumer_receipt
from m2riv.core.identity import fingerprint
from m2riv.core.models import ModelSnapshot
from m2riv.reports import MCRDecision, MCRStatus, create_report, write_report_bundle

runner = CliRunner()


def test_inspect_outputs_valid_snapshot(tmp_path: Path) -> None:
    artifact = tmp_path / "model.bin"
    artifact.write_bytes(b"weights")

    result = runner.invoke(app, ["inspect", str(artifact), "--family", "cv"])

    assert result.exit_code == 0
    snapshot = ModelSnapshot.model_validate_json(result.stdout)
    assert snapshot.model_family.value == "cv"


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip()


def test_schema_export(tmp_path: Path) -> None:
    destination = tmp_path / "schemas"
    result = runner.invoke(app, ["schema", "export", str(destination)])

    assert result.exit_code == 0
    generated = sorted(destination.glob("*.schema.json"))
    assert len(generated) == 24
    assert any(path.name == "ModelSnapshot.schema.json" for path in generated)
    assert any(path.name == "CompiledReleasePlan.schema.json" for path in generated)
    assert any(path.name == "PluginManifest.schema.json" for path in generated)
    assert any(path.name == "ArtifactProfile.schema.json" for path in generated)
    assert any(path.name == "ArtifactDiff.schema.json" for path in generated)
    assert any(path.name == "EvidenceManifest.schema.json" for path in generated)
    assert any(path.name == "MCRVerification.schema.json" for path in generated)
    assert any(path.name == "ConsumerConformanceReceipt.schema.json" for path in generated)
    assert any(path.name == "MCRConformanceResult.schema.json" for path in generated)
    assert any(path.name == "BackendComparisonEvidence.schema.json" for path in generated)
    committed = sorted(Path("schemas/v1").glob("*.schema.json"))
    assert [path.name for path in committed] == [path.name for path in generated]
    for expected, actual in zip(committed, generated, strict=True):
        assert actual.read_text(encoding="utf-8") == expected.read_text(encoding="utf-8")


def test_mcr_verify_command_returns_machine_readable_result(tmp_path: Path) -> None:
    report = create_report(
        baseline_snapshot_id=f"m2riv:sha256:{fingerprint('b', namespace='cli-test')}",
        candidate_snapshot_id=f"m2riv:sha256:{fingerprint('c', namespace='cli-test')}",
        metrics=(),
        decision=MCRDecision(status=MCRStatus.PASS, allowed=True),
    )
    write_report_bundle(report, tmp_path)

    result = runner.invoke(app, ["mcr", "verify", str(tmp_path)])

    assert result.exit_code == 0
    assert '"valid": true' in result.stdout
    assert '"decision_status": "PASS"' in result.stdout


def test_mcr_verify_command_fails_closed_on_tampering(tmp_path: Path) -> None:
    invalid = tmp_path / "m2riv-report.json"
    invalid.write_text("{}", encoding="utf-8")
    result = runner.invoke(app, ["mcr", "verify", str(invalid)])
    assert result.exit_code == 3
    assert '"valid": false' in result.stdout


def test_producer_and_consumer_conformance_commands(tmp_path: Path) -> None:
    fixture_root = Path("examples/mcr_conformance")
    producer = runner.invoke(app, ["conformance", "producer", str(fixture_root)])
    assert producer.exit_code == 0
    assert '"subject": "producer"' in producer.stdout

    profiles = []
    for name, status, authorized in (
        ("pass", "PASS", True),
        ("warn", "WARN", False),
        ("block", "BLOCK", False),
    ):
        verified = runner.invoke(app, ["mcr", "verify", str(fixture_root / name)])
        payload = json.loads(verified.stdout)
        profiles.append(
            ConformanceProfile(
                profile=name,
                report_id=payload["report_id"],
                decision_status=status,
                release_authorized=authorized,
            )
        )
    receipt = create_consumer_receipt(
        implementation_name="example.consumer",
        implementation_version="1.0",
        profiles=tuple(profiles),
    )
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(receipt.model_dump_json(indent=2), encoding="utf-8")
    consumer = runner.invoke(
        app,
        [
            "conformance",
            "consumer",
            str(receipt_path),
            "--fixtures",
            str(fixture_root),
        ],
    )
    assert consumer.exit_code == 0
    assert '"subject": "consumer"' in consumer.stdout
    assert '"warn-and-block-fail-closed"' in consumer.stdout


def test_artifact_commands_report_invalid_inputs(tmp_path: Path) -> None:
    artifact = tmp_path / "not-onnx.bin"
    artifact.write_bytes(b"not an ONNX graph")
    suite = tmp_path / "suite.jsonl"
    suite.write_text('{"case_id":"one","input":[1]}\n', encoding="utf-8")

    for arguments in (
        ["artifact", "inspect", str(artifact), "--max-artifact-bytes", "1"],
        [
            "artifact",
            "diff",
            str(artifact),
            str(artifact),
            "--max-artifact-bytes",
            "1",
        ],
        [
            "artifact",
            "numerical-diff",
            str(artifact),
            str(artifact),
            "--suite",
            str(suite),
        ],
    ):
        result = runner.invoke(app, arguments)
        assert result.exit_code == 3
        assert "ERROR:" in result.stderr


def test_plan_command_reports_invalid_policy(tmp_path: Path) -> None:
    policy = tmp_path / "policy.yaml"
    policy.write_text("{}\n", encoding="utf-8")
    suite = tmp_path / "suite.jsonl"
    suite.write_text('{"case_id":"one","input":1}\n', encoding="utf-8")

    result = runner.invoke(app, ["plan", "--suite", str(suite), "--policy", str(policy)])

    assert result.exit_code == 3
    assert "ERROR:" in result.stderr
