from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from merriv.cli import app
from merriv.core.identity import build_local_snapshot, hash_artifact
from merriv.core.models import EvidenceRef, RuntimeProfile
from merriv.evidence import (
    BackendCaseComparison,
    FileDigestBinding,
    create_backend_comparison_evidence,
    create_build_provenance_evidence,
    create_snapshot_artifact_manifest,
    create_tool_native_evidence,
)
from merriv.reports import (
    MCRDecision,
    MCRStatus,
    MCRVerificationError,
    create_report,
    verify_report_bundle,
    write_report_bundle,
)
from merriv.target import (
    TargetEvidenceManifest,
    TargetReportBinding,
    create_target_evidence_manifest,
    verify_target_evidence_manifest,
    write_target_evidence_manifest,
)


def _write_contract(path: Path, value: object) -> None:
    path.write_text(value.model_dump_json(indent=2) + "\n", encoding="utf-8")  # type: ignore[attr-defined]


def _complete_bundle(root: Path) -> tuple[Path, str]:
    root.mkdir(parents=True, exist_ok=True)
    onnx = root / "model.onnx"
    engine = root / "model.engine"
    raw = root / "polygraphy.json"
    onnx.write_bytes(b"onnx-artifact")
    engine.write_bytes(b"engine-artifact")
    raw.write_bytes(b'{"native":"polygraphy"}\n')
    profile = RuntimeProfile(framework="TensorRT", framework_version="10.4", device="gpu")
    onnx_snapshot = build_local_snapshot(onnx, runtime_profile=profile)
    engine_snapshot = build_local_snapshot(engine, runtime_profile=profile)
    onnx_digest = hash_artifact(onnx)
    engine_digest = hash_artifact(engine)
    native = create_tool_native_evidence(
        raw,
        uri=raw.name,
        producer_name="nvidia.polygraphy",
        producer_version="0.53.4",
        media_type="application/vnd.nvidia.polygraphy.run-results+json",
        purpose="backend parity",
        exit_code=0,
        runner_names=("onnxrt-runner", "trt-runner"),
    )
    backend = create_backend_comparison_evidence(
        comparator_name="nvidia.polygraphy",
        comparator_version="0.53.4",
        comparator_exit_code=0,
        baseline_runner="onnxrt-runner",
        candidate_runner="trt-runner",
        tool_native_evidence_id=native.id,
        baseline_snapshot_id=onnx_snapshot.id,
        candidate_snapshot_id=engine_snapshot.id,
        absolute_tolerance=0.05,
        relative_tolerance=0.01,
        comparisons=(BackendCaseComparison(case_id="case-1", output_matches={"logits": True}),),
        runtime_profile=profile,
    )
    onnx_manifest = create_snapshot_artifact_manifest(
        onnx_snapshot,
        (
            FileDigestBinding(
                uri=onnx.name,
                sha256=onnx_digest.digest,
                size_bytes=onnx_digest.size_bytes,
                logical_name=onnx.name,
            ),
        ),
    )
    engine_manifest = create_snapshot_artifact_manifest(
        engine_snapshot,
        (
            FileDigestBinding(
                uri=engine.name,
                sha256=engine_digest.digest,
                size_bytes=engine_digest.size_bytes,
                logical_name=engine.name,
            ),
        ),
    )
    build = create_build_provenance_evidence(
        build_name="build-01",
        builder_name="nvidia-tensorrt",
        builder_version="10.4.0",
        input_artifacts=(onnx_digest,),
        output_artifacts=(engine_digest,),
        output_snapshot_id=engine_snapshot.id,
        parameters={"calibration_input_scale": 1.0},
    )
    items = (
        ("tool-native-evidence", "tool-native.json", native),
        ("backend-comparison", "backend.json", backend),
        ("snapshot-artifact-manifest", "onnx-snapshot.json", onnx_manifest),
        ("snapshot-artifact-manifest", "engine-snapshot.json", engine_manifest),
        ("build-provenance", "build.json", build),
    )
    report = create_report(
        baseline_snapshot_id=onnx_snapshot.id,
        candidate_snapshot_id=engine_snapshot.id,
        metrics=(),
        decision=MCRDecision(status=MCRStatus.PASS, allowed=True),
        evidence=tuple(EvidenceRef(id=item.id, kind=kind, uri=name) for kind, name, item in items),
    )
    write_report_bundle(report, root)
    for _, name, item in items:
        _write_contract(root / name, item)
    return raw, report.id


def test_native_snapshot_and_build_evidence_form_one_strict_chain(tmp_path: Path) -> None:
    raw, _ = _complete_bundle(tmp_path)
    verified = verify_report_bundle(tmp_path, require_complete=True)
    assert verified.bundle_verification_complete is True
    assert verified.evidence_body_coverage.verified_structured == 4
    assert verified.evidence_body_coverage.verified_opaque == 1
    assert verified.evidence_body_coverage.coverage == 1.0

    raw.write_bytes(b'{"native":"poisoned"}\n')
    with pytest.raises(MCRVerificationError, match="digest or size"):
        verify_report_bundle(tmp_path, require_complete=True)


def test_build_identity_changes_with_release_relevant_dimension(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"artifact")
    digest = hash_artifact(artifact)
    snapshot = build_local_snapshot(artifact)
    first = create_build_provenance_evidence(
        build_name="build",
        builder_name="nvidia-modelopt",
        builder_version="0.46.0",
        input_artifacts=(digest,),
        output_artifacts=(digest,),
        output_snapshot_id=snapshot.id,
        parameters={"calibration_input_scale": 1.0},
    )
    bad = create_build_provenance_evidence(
        build_name="build",
        builder_name="nvidia-modelopt",
        builder_version="0.46.0",
        input_artifacts=(digest,),
        output_artifacts=(digest,),
        output_snapshot_id=snapshot.id,
        parameters={"calibration_input_scale": 0.65},
    )
    assert first.id != bad.id


def test_target_root_detects_changed_or_unlisted_files(tmp_path: Path) -> None:
    report_root = tmp_path / "reports" / "build-01"
    _complete_bundle(report_root)
    profile = RuntimeProfile(framework="TensorRT", framework_version="10.4", device="gpu")
    manifest = create_target_evidence_manifest(
        root=tmp_path,
        source_commit="a" * 40,
        target_profile=profile,
        tool_versions={"tensorrt": "10.4.0"},
        report_builds=(("build-01", "reports/build-01"),),
        first_bad_build=None,
    )
    write_target_evidence_manifest(manifest, tmp_path / "target-evidence-manifest.json")
    verified = verify_target_evidence_manifest(tmp_path)
    assert verified.target_evidence_id == manifest.id

    engine = report_root / "model.engine"
    engine.write_bytes(b"poison-artfact")
    with pytest.raises(MCRVerificationError, match="digest changed"):
        verify_target_evidence_manifest(tmp_path)
    engine.write_bytes(b"engine-artifact")

    extra = tmp_path / "unlisted.txt"
    extra.write_text("unlisted", encoding="utf-8")
    with pytest.raises(MCRVerificationError, match="missing or unlisted"):
        verify_target_evidence_manifest(tmp_path)


def test_target_root_cannot_hide_cache_or_nested_manifest_bytes(tmp_path: Path) -> None:
    _complete_bundle(tmp_path / "reports" / "build-01")
    profile = RuntimeProfile(framework="TensorRT", framework_version="10.4", device="gpu")
    manifest = create_target_evidence_manifest(
        root=tmp_path,
        source_commit="b" * 40,
        target_profile=profile,
        tool_versions={"tensorrt": "10.4.0"},
        report_builds=(("build-01", "reports/build-01"),),
        first_bad_build=None,
    )
    write_target_evidence_manifest(manifest, tmp_path / "target-evidence-manifest.json")

    cache_file = tmp_path / ".cache" / "poisoned.json"
    cache_file.parent.mkdir()
    cache_file.write_text("poisoned", encoding="utf-8")
    with pytest.raises(MCRVerificationError, match="missing or unlisted"):
        verify_target_evidence_manifest(tmp_path)

    cache_file.unlink()
    cache_file.parent.rmdir()
    nested = tmp_path / "retained" / "target-evidence-manifest.json"
    nested.parent.mkdir()
    nested.write_text("unlisted nested bytes", encoding="utf-8")
    with pytest.raises(MCRVerificationError, match="missing or unlisted"):
        verify_target_evidence_manifest(tmp_path)


def test_target_cli_and_manifest_identity_fail_closed(tmp_path: Path) -> None:
    _complete_bundle(tmp_path / "reports" / "build-01")
    manifest = create_target_evidence_manifest(
        root=tmp_path,
        source_commit="c" * 40,
        target_profile=RuntimeProfile(framework="TensorRT", device="gpu"),
        tool_versions={"tensorrt": "10.4.0"},
        report_builds=(("build-01", "reports/build-01"),),
        first_bad_build=None,
    )
    manifest_path = tmp_path / "target-evidence-manifest.json"
    write_target_evidence_manifest(manifest, manifest_path)
    runner = CliRunner()
    success = runner.invoke(app, ["mcr", "verify-target", str(manifest_path)])
    assert success.exit_code == 0
    assert json.loads(success.stdout)["target_evidence_id"] == manifest.id

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["id"] = "mcr:sha256:" + "d" * 64
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    failure = runner.invoke(app, ["mcr", "verify-target", str(tmp_path)])
    assert failure.exit_code == 3
    assert json.loads(failure.stdout)["valid"] is False


def test_target_contract_rejects_duplicate_bindings_and_unsafe_directories(tmp_path: Path) -> None:
    _complete_bundle(tmp_path / "reports" / "build-01")
    manifest = create_target_evidence_manifest(
        root=tmp_path,
        source_commit="e" * 40,
        target_profile=RuntimeProfile(framework="TensorRT", device="gpu"),
        tool_versions={"tensorrt": "10.4.0"},
        report_builds=(("build-01", "reports/build-01"),),
        first_bad_build=None,
    )
    payload = manifest.model_dump(mode="python")
    payload["files"] = (*manifest.files, manifest.files[0])
    with pytest.raises(ValidationError, match="file URIs must be unique"):
        TargetEvidenceManifest.model_validate(payload)
    duplicate_reports = manifest.model_dump(mode="python")
    duplicate_reports["reports"] = (*manifest.reports, manifest.reports[0])
    with pytest.raises(ValidationError, match="report build names must be unique"):
        TargetEvidenceManifest.model_validate(duplicate_reports)
    with pytest.raises(ValidationError, match="safe and relative"):
        TargetReportBinding(
            build_name="build",
            directory="../escape",
            report_id=manifest.reports[0].report_id,
            evidence_id=manifest.reports[0].evidence_id,
            run_id=manifest.reports[0].run_id,
        )

    broken = tmp_path / "broken-target-evidence-manifest.json"
    broken.write_bytes(b"{")
    with pytest.raises(MCRVerificationError, match="unavailable or invalid"):
        verify_target_evidence_manifest(broken)
