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
    assert len(generated) == 31
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
    assert any(path.name == "MCRInTotoStatement.schema.json" for path in generated)
    assert any(path.name == "MCRArtifactManifest.schema.json" for path in generated)
    committed = sorted(Path("schemas/mcr-0.4").glob("*.schema.json"))
    assert [path.name for path in committed] == [path.name for path in generated]
    for expected, actual in zip(committed, generated, strict=True):
        assert actual.read_text(encoding="utf-8") == expected.read_text(encoding="utf-8")


def test_mcr_verify_command_returns_machine_readable_result(tmp_path: Path) -> None:
    report = create_report(
        baseline_snapshot_id=f"mcr:sha256:{fingerprint('b', namespace='cli-test')}",
        candidate_snapshot_id=f"mcr:sha256:{fingerprint('c', namespace='cli-test')}",
        metrics=(),
        decision=MCRDecision(status=MCRStatus.PASS, allowed=True),
    )
    write_report_bundle(report, tmp_path)

    result = runner.invoke(app, ["mcr", "verify", str(tmp_path)])

    assert result.exit_code == 0
    assert '"valid": true' in result.stdout
    assert '"decision_status": "PASS"' in result.stdout
    assert '"producer_authenticated": false' in result.stdout
    assert '"deployment_authorization": "not-evaluated"' in result.stdout


def test_mcr_verify_command_fails_closed_on_tampering(tmp_path: Path) -> None:
    invalid = tmp_path / "mcr-report.json"
    invalid.write_text("{}", encoding="utf-8")
    result = runner.invoke(app, ["mcr", "verify", str(invalid)])
    assert result.exit_code == 3
    assert '"valid": false' in result.stdout


def test_mcr_predicate_emits_cosign_predicate_body(tmp_path: Path) -> None:
    report = create_report(
        baseline_snapshot_id=f"mcr:sha256:{fingerprint('b', namespace='predicate-test')}",
        candidate_snapshot_id=f"mcr:sha256:{fingerprint('c', namespace='predicate-test')}",
        metrics=(),
        decision=MCRDecision(status=MCRStatus.PASS, allowed=True),
    )
    write_report_bundle(report, tmp_path)

    result = runner.invoke(
        app,
        [
            "mcr",
            "predicate",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    predicate = json.loads(result.stdout)
    assert predicate["predicate_version"] == "0.1.0"
    assert predicate["report"]["id"] == report.id


def test_mcr_statement_and_oci_layout_bind_the_external_subject(tmp_path: Path) -> None:
    report = create_report(
        baseline_snapshot_id=f"mcr:sha256:{fingerprint('b', namespace='oci-test')}",
        candidate_snapshot_id=f"mcr:sha256:{fingerprint('c', namespace='oci-test')}",
        metrics=(),
        decision=MCRDecision(status=MCRStatus.PASS, allowed=True),
    )
    bundle = tmp_path / "bundle"
    write_report_bundle(report, bundle)
    subject_sha256 = "a" * 64

    statement_result = runner.invoke(
        app,
        [
            "mcr",
            "statement",
            str(bundle),
            "--subject-name",
            "registry.example/model:v2",
            "--subject-sha256",
            subject_sha256,
        ],
    )
    assert statement_result.exit_code == 0
    statement = json.loads(statement_result.stdout)
    assert statement["_type"] == "https://in-toto.io/Statement/v1"
    assert statement["subject"][0]["digest"]["sha256"] == subject_sha256
    assert statement["predicate"]["report"]["id"] == report.id

    layout = tmp_path / "oci"
    layout_result = runner.invoke(
        app,
        [
            "mcr",
            "oci-layout",
            str(bundle),
            "--subject-name",
            "registry.example/model:v2",
            "--subject-digest",
            f"sha256:{subject_sha256}",
            "--subject-size",
            "1234",
            "--output",
            str(layout),
        ],
    )
    assert layout_result.exit_code == 0
    result_payload = json.loads(layout_result.stdout)
    assert result_payload["deployment_authorization"] == "not-evaluated"
    index = json.loads((layout / "index.json").read_text("utf-8"))
    manifest_digest = index["manifests"][0]["digest"].removeprefix("sha256:")
    manifest = json.loads((layout / "blobs" / "sha256" / manifest_digest).read_text("utf-8"))
    assert manifest["subject"]["digest"] == f"sha256:{subject_sha256}"
    assert manifest["artifactType"] == "application/vnd.in-toto.mcr+json"
    statement_digest = manifest["layers"][0]["digest"].removeprefix("sha256:")
    retained_statement = json.loads(
        (layout / "blobs" / "sha256" / statement_digest).read_text("utf-8")
    )
    assert retained_statement["predicate"]["report"]["id"] == report.id


def test_producer_and_consumer_conformance_commands(tmp_path: Path) -> None:
    fixture_root = Path("examples/mcr_conformance")
    producer = runner.invoke(app, ["conformance", "producer", str(fixture_root)])
    assert producer.exit_code == 0
    assert '"subject": "producer"' in producer.stdout

    profiles = []
    for name, status, authorized in (
        ("pass", "PASS", True),
        ("warn", "WARN", False),
        ("insufficient_power", "INSUFFICIENT_POWER", False),
        ("block", "BLOCK", False),
        ("error", "ERROR", False),
    ):
        verified = runner.invoke(app, ["mcr", "verify", str(fixture_root / name)])
        payload = json.loads(verified.stdout)
        profiles.append(
            ConformanceProfile(
                profile=name,
                report_id=payload["report_id"],
                evidence_id=payload["evidence_id"],
                decision_status=status,
                evaluation_policy_satisfied=authorized,
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
    assert '"warn-insufficient-power-block-error-fail-closed"' in consumer.stdout


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
