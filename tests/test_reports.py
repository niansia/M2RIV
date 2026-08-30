from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

import pytest
from pydantic import ValidationError

from merriv.artifacts import ArtifactDiff, NumericalDiff, TensorNumericalDiff
from merriv.core.identity import fingerprint
from merriv.core.models import EvidenceRef, RuntimeProfile
from merriv.planning import CompiledReleasePlan, PlannedMetric, RuleBinding
from merriv.reports import (
    EvidenceManifest,
    EvidenceManifestRef,
    EvidenceSet,
    MCRDecision,
    MCRExecution,
    MCRFinding,
    MCRMetric,
    MCRStatus,
    MCRVerificationError,
    ModelChangeReport,
    create_evidence_manifest,
    create_evidence_set,
    create_report,
    render_json,
    render_junit,
    render_markdown,
    render_sarif,
    verify_report_bundle,
    write_report_bundle,
)
from merriv.reports import verify as report_verifier


def content_id(label: str) -> str:
    return f"mcr:sha256:{fingerprint(label, namespace='report-test')}"


def sample_report() -> ModelChangeReport:
    return create_report(
        baseline_snapshot_id=content_id("baseline"),
        candidate_snapshot_id=content_id("candidate"),
        metrics=(
            MCRMetric(
                metric_id="rare_class_recall",
                scope="slice:rare",
                baseline_value=1.0,
                candidate_value=0.4,
                delta=-0.6,
                confidence_level=0.95,
                interval_lower=-0.9,
                interval_upper=-0.2,
                sample_size=10,
            ),
        ),
        decision=MCRDecision(status=MCRStatus.BLOCK, allowed=False),
        limitations=("Synthetic fixture",),
        created_at=datetime(2026, 8, 28, tzinfo=UTC),
    )


def sample_plan() -> CompiledReleasePlan:
    digest = "1" * 64
    plan = CompiledReleasePlan(
        id=content_id("placeholder-plan"),
        policy_id="external-policy",
        policy_fingerprint=digest,
        suite_fingerprint="2" * 64,
        runtime_profile_fingerprint="3" * 64,
        seed=0,
        resamples=100,
        confidence_level=0.95,
        metrics=(
            PlannedMetric(
                metric_id="accuracy",
                base_metric_id="accuracy",
                scope="overall",
                direction="higher_is_better",
                unit="fraction",
                binary=True,
            ),
        ),
        bindings=(
            RuleBinding(
                rule_id="accuracy-floor",
                metric_id="accuracy",
                base_metric_id="accuracy",
            ),
        ),
    )
    identifier = fingerprint(
        plan.model_dump(mode="python", exclude={"id"}), namespace="release-plan"
    )
    return plan.model_copy(update={"id": f"mcr:sha256:{identifier}"})


def sample_numerical_diff() -> NumericalDiff:
    item = NumericalDiff(
        id=content_id("placeholder-numerical"),
        baseline_profile_id=content_id("numerical-baseline"),
        candidate_profile_id=content_id("numerical-candidate"),
        case_count=1,
        absolute_tolerance=0.001,
        relative_tolerance=0.001,
        tensors=(
            TensorNumericalDiff(
                name="logits",
                baseline_dtype="float32",
                candidate_dtype="float32",
                shape=(1, 2),
                element_count=2,
                max_abs_error=0.01,
                mean_abs_error=0.005,
                rmse=0.007,
                max_relative_error=0.01,
                cosine_similarity=0.99,
                within_tolerance=False,
            ),
        ),
        first_divergent_tensor="logits",
    )
    identifier = fingerprint(
        item.model_dump(mode="python", exclude={"schema_version", "id"}),
        namespace="onnx-numerical-diff",
    )
    return item.model_copy(update={"id": f"mcr:sha256:{identifier}"})


def write_raw_bundle(
    root: Path,
    report: ModelChangeReport,
    *,
    manifest: EvidenceManifest | None = None,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "mcr-report.json").write_text(render_json(report), encoding="utf-8")
    if manifest is not None:
        (root / "evidence-manifest.json").write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )


def test_report_round_trip_and_stable_identity() -> None:
    report = sample_report()
    assert report.schema_version == "0.4.0"
    assert ModelChangeReport.model_validate_json(render_json(report)) == report
    assert sample_report().id == report.id


def test_evidence_identity_excludes_timestamp_and_run_scoped_metrics() -> None:
    first = create_report(
        baseline_snapshot_id=content_id("baseline-stable"),
        candidate_snapshot_id=content_id("candidate-stable"),
        metrics=(
            MCRMetric(
                metric_id="accuracy",
                baseline_value=1.0,
                candidate_value=0.9,
                delta=-0.1,
                sample_size=10,
            ),
            MCRMetric(
                metric_id="mean_latency_ms",
                unit="milliseconds",
                direction="lower_is_better",
                baseline_value=1.0,
                candidate_value=2.0,
                delta=1.0,
                sample_size=10,
                identity_scope="run",
            ),
        ),
        decision=MCRDecision(status=MCRStatus.BLOCK, allowed=False),
        created_at=datetime(2026, 8, 28, tzinfo=UTC),
    )
    second = create_report(
        baseline_snapshot_id=content_id("baseline-stable"),
        candidate_snapshot_id=content_id("candidate-stable"),
        metrics=(
            first.metrics[0],
            first.metrics[1].model_copy(update={"baseline_value": 1.5, "candidate_value": 2.5}),
        ),
        decision=first.decision,
        created_at=datetime(2026, 8, 29, tzinfo=UTC),
    )

    assert first.evidence_id == second.evidence_id
    assert first.id == second.id
    assert first.run_id != second.run_id


def test_opposite_verdicts_share_evidence_but_never_report_identity() -> None:
    blocked = sample_report()
    passed = create_report(
        baseline_snapshot_id=blocked.baseline_snapshot_id,
        candidate_snapshot_id=blocked.candidate_snapshot_id,
        metrics=blocked.metrics,
        decision=MCRDecision(status=MCRStatus.PASS, allowed=True),
        limitations=blocked.limitations,
        created_at=blocked.created_at,
    )
    assert blocked.evidence_id == passed.evidence_id
    assert blocked.id != passed.id
    assert blocked.run_id != passed.run_id


def test_markdown_surfaces_decision_and_slice() -> None:
    markdown = render_markdown(sample_report())
    assert "**Evaluation decision: BLOCK**" in markdown
    assert "Deployment authorization: `not-evaluated`" in markdown
    assert "rare_class_recall" in markdown
    assert "slice:rare" in markdown


def test_partial_or_reversed_interval_is_rejected() -> None:
    with pytest.raises(ValidationError, match="provided together"):
        MCRMetric(
            metric_id="accuracy",
            baseline_value=1,
            candidate_value=0.9,
            delta=-0.1,
            interval_lower=-0.2,
            sample_size=5,
        )
    with pytest.raises(ValidationError, match="must not exceed"):
        MCRMetric(
            metric_id="accuracy",
            baseline_value=1,
            candidate_value=0.9,
            delta=-0.1,
            confidence_level=0.95,
            interval_lower=0.2,
            interval_upper=-0.2,
            sample_size=5,
        )


def test_release_disposition_matches_terminal_statuses() -> None:
    for status in (MCRStatus.ERROR, MCRStatus.BLOCK, MCRStatus.INSUFFICIENT_POWER):
        with pytest.raises(ValidationError, match="allowed must be False"):
            MCRDecision(status=status, allowed=True)
    with pytest.raises(ValidationError, match="allowed must be True"):
        MCRDecision(status=MCRStatus.PASS, allowed=False)
    assert MCRDecision(status=MCRStatus.WARN, allowed=False).allowed is False
    assert MCRDecision(status=MCRStatus.WARN, allowed=True).allowed is True


def test_report_bundle_is_written_with_canonical_names(tmp_path: Path) -> None:
    report = sample_report()
    bundle = write_report_bundle(report, tmp_path)
    assert bundle.plan_path is None
    assert bundle.evidence_manifest_path is None
    assert bundle.json_path.name == "mcr-report.json"
    assert bundle.markdown_path.name == "summary.md"
    assert bundle.junit_path.name == "junit.xml"
    assert bundle.sarif_path.name == "results.sarif"
    assert ModelChangeReport.model_validate_json(bundle.json_path.read_text("utf-8")) == report
    assert "Evaluation decision: BLOCK" in bundle.markdown_path.read_text("utf-8")
    with pytest.raises(ValueError, match="MCR identity"):
        write_report_bundle(
            report.model_copy(update={"run_id": content_id("tampered-run")}),
            tmp_path / "tampered-report",
        )


def test_standalone_verifier_detects_report_tampering(tmp_path: Path) -> None:
    bundle = write_report_bundle(sample_report(), tmp_path)
    verified = verify_report_bundle(tmp_path)
    assert verified.valid is True
    assert verified.integrity_valid is True
    assert verified.bundle_verification_complete is True
    assert verified.evidence_body_coverage.declared == 0
    assert verified.evidence_body_coverage.coverage == 1.0
    assert verified.decision_status == "BLOCK"
    assert {"report-contract", "evidence-id", "report-id", "run-id"}.issubset(
        verified.checks
    )

    payload = json.loads(bundle.json_path.read_text("utf-8"))
    payload["metrics"][0]["candidate_value"] = 0.5
    bundle.json_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MCRVerificationError, match="identity does not match"):
        verify_report_bundle(bundle.json_path)


def test_standalone_verifier_rehashes_known_supplemental_evidence(
    tmp_path: Path,
) -> None:
    placeholder = content_id("placeholder-diff")
    artifact_diff = ArtifactDiff(
        id=placeholder,
        baseline_profile_id=content_id("baseline-profile"),
        candidate_profile_id=content_id("candidate-profile"),
        artifact_changed=True,
        format_changed=False,
        size_delta_bytes=5,
        file_count_delta=0,
    )
    identifier = fingerprint(
        artifact_diff.model_dump(mode="python", exclude={"schema_version", "id"}),
        namespace="artifact-diff",
    )
    artifact_diff = artifact_diff.model_copy(update={"id": f"mcr:sha256:{identifier}"})
    evidence = EvidenceRef(
        id=artifact_diff.id,
        kind="artifact-diff",
        uri="artifact-diff.json",
    )
    report = create_report(
        baseline_snapshot_id=content_id("supplemental-baseline"),
        candidate_snapshot_id=content_id("supplemental-candidate"),
        metrics=(),
        decision=MCRDecision(status=MCRStatus.WARN, allowed=False),
        evidence=(evidence,),
    )
    write_report_bundle(report, tmp_path)
    evidence_path = tmp_path / "artifact-diff.json"
    evidence_path.write_text(artifact_diff.model_dump_json(indent=2), encoding="utf-8")

    verified = verify_report_bundle(tmp_path)
    assert "supplemental-id:artifact-diff" in verified.checks
    assert verified.bundle_verification_complete is True
    assert verified.evidence_body_coverage.verified_structured == 1
    assert verified.evidence_body_coverage.coverage == 1.0
    tampered = json.loads(evidence_path.read_text("utf-8"))
    tampered["size_delta_bytes"] = 99
    evidence_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(MCRVerificationError, match="does not match its contents"):
        verify_report_bundle(tmp_path)


def test_verifier_checks_plan_numerical_diff_and_warning_boundaries(
    tmp_path: Path,
) -> None:
    plan = sample_plan()
    numerical = sample_numerical_diff()
    unknown_id = content_id("unknown-evidence")
    report = create_report(
        baseline_snapshot_id=content_id("rich-baseline"),
        candidate_snapshot_id=content_id("rich-candidate"),
        release_plan_id=plan.id,
        executions=(
            MCRExecution(
                role="candidate",
                executor_id="external",
                executor_version="1",
                config_fingerprint="4" * 64,
                runtime_profile=RuntimeProfile(
                    framework="fixture", operating_system="test", architecture="generic"
                ),
                requested_cases=1,
                returned_observations=1,
            ),
        ),
        metrics=(),
        decision=MCRDecision(status=MCRStatus.WARN, allowed=False),
        evidence=(
            EvidenceRef(id=numerical.id, kind="numerical-diff", uri="numerical.json"),
            EvidenceRef(id=unknown_id, kind="external-note", uri="note.json"),
            EvidenceRef(
                id=content_id("remote"),
                kind="external-note",
                uri="https://example.invalid/evidence.json",
            ),
            EvidenceRef(id=content_id("redacted"), kind="trace", redacted=True),
        ),
    )
    write_report_bundle(report, tmp_path, release_plan=plan)
    (tmp_path / "numerical.json").write_text(numerical.model_dump_json(indent=2), encoding="utf-8")
    (tmp_path / "note.json").write_text(json.dumps({"id": unknown_id}), encoding="utf-8")

    verified = verify_report_bundle(tmp_path)

    assert "release-plan-id" in verified.checks
    assert "supplemental-id:numerical-diff" in verified.checks
    assert len(verified.warnings) == 1
    assert verified.bundle_verification_complete is False
    assert verified.evidence_body_coverage.verified_structured == 1
    assert verified.evidence_body_coverage.unrecognized_local == 1
    assert verified.evidence_body_coverage.remote == 1
    assert verified.evidence_body_coverage.redacted == 1


def test_verifier_rejects_missing_malformed_and_oversized_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(MCRVerificationError, match="unavailable"):
        verify_report_bundle(tmp_path / "missing.json")

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    with pytest.raises(MCRVerificationError, match="not valid UTF-8 JSON"):
        verify_report_bundle(malformed)

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")
    with pytest.raises(MCRVerificationError, match="does not match its contract"):
        verify_report_bundle(invalid)

    valid = tmp_path / "valid"
    write_report_bundle(sample_report(), valid)
    monkeypatch.setattr(report_verifier, "MAX_JSON_FILE_BYTES", 1)
    with pytest.raises(MCRVerificationError, match="JSON size limit"):
        verify_report_bundle(valid)
    monkeypatch.setattr(report_verifier, "MAX_JSON_FILE_BYTES", 16 * 1024 * 1024)
    monkeypatch.setattr(report_verifier, "MAX_BUNDLE_JSON_BYTES", 1)
    with pytest.raises(MCRVerificationError, match="total JSON size limit"):
        verify_report_bundle(valid)


def test_verifier_rejects_unsafe_or_mismatched_supplemental_evidence(
    tmp_path: Path,
) -> None:
    escaped = EvidenceRef(id=content_id("escaped"), kind="external-note", uri="../outside.json")
    escaped_report = create_report(
        baseline_snapshot_id=content_id("escaped-baseline"),
        candidate_snapshot_id=content_id("escaped-candidate"),
        metrics=(),
        decision=MCRDecision(status=MCRStatus.PASS, allowed=True),
        evidence=(escaped,),
    )
    write_report_bundle(escaped_report, tmp_path / "escaped")
    with pytest.raises(MCRVerificationError, match="safe relative path"):
        verify_report_bundle(tmp_path / "escaped")

    mismatch = EvidenceRef(id=content_id("expected-body"), kind="external-note", uri="note.json")
    mismatch_report = create_report(
        baseline_snapshot_id=content_id("mismatch-baseline"),
        candidate_snapshot_id=content_id("mismatch-candidate"),
        metrics=(),
        decision=MCRDecision(status=MCRStatus.PASS, allowed=True),
        evidence=(mismatch,),
    )
    write_report_bundle(mismatch_report, tmp_path / "mismatch")
    (tmp_path / "mismatch" / "note.json").write_text(
        json.dumps({"id": content_id("wrong-body")}), encoding="utf-8"
    )
    with pytest.raises(MCRVerificationError, match="does not match its reference"):
        verify_report_bundle(tmp_path / "mismatch")

    invalid_numerical = EvidenceRef(
        id=content_id("invalid-numerical"),
        kind="numerical-diff",
        uri="numerical.json",
    )
    invalid_report = create_report(
        baseline_snapshot_id=content_id("invalid-num-baseline"),
        candidate_snapshot_id=content_id("invalid-num-candidate"),
        metrics=(),
        decision=MCRDecision(status=MCRStatus.PASS, allowed=True),
        evidence=(invalid_numerical,),
    )
    write_report_bundle(invalid_report, tmp_path / "invalid-numerical")
    (tmp_path / "invalid-numerical" / "numerical.json").write_text(
        json.dumps({"id": invalid_numerical.id}), encoding="utf-8"
    )
    with pytest.raises(MCRVerificationError, match="does not match its contract"):
        verify_report_bundle(tmp_path / "invalid-numerical")


def test_external_evidence_manifest_is_content_addressed_and_validated(tmp_path: Path) -> None:
    references = (
        EvidenceRef(id=content_id("obs-a"), kind="observation"),
        EvidenceRef(id=content_id("obs-b"), kind="observation"),
    )
    evidence_set = create_evidence_set(references)
    manifest = create_evidence_manifest(references, (evidence_set,))
    manifest_ref = EvidenceManifestRef(
        id=manifest.id,
        evidence_count=len(manifest.evidence),
        set_count=len(manifest.sets),
    )
    report = create_report(
        baseline_snapshot_id=content_id("baseline-manifest"),
        candidate_snapshot_id=content_id("candidate-manifest"),
        metrics=(
            MCRMetric(
                metric_id="accuracy",
                baseline_value=1.0,
                candidate_value=1.0,
                delta=0.0,
                sample_size=1,
                evidence_set_id=evidence_set.id,
            ),
        ),
        decision=MCRDecision(status=MCRStatus.PASS, allowed=True),
        evidence_manifest=manifest_ref,
    )

    bundle = write_report_bundle(report, tmp_path, evidence_manifest=manifest)
    assert bundle.evidence_manifest_path is not None
    assert (
        EvidenceManifest.model_validate_json(bundle.evidence_manifest_path.read_text("utf-8"))
        == manifest
    )
    assert "evidence-manifest.json" in bundle.markdown_path.read_text("utf-8")
    verified = verify_report_bundle(tmp_path)
    assert "manifest-id" in verified.checks
    assert "evidence-set-ids" in verified.checks

    tampered = manifest.model_copy(update={"id": content_id("tampered")})
    with pytest.raises(ValueError, match="identity does not match its contents"):
        write_report_bundle(report, tmp_path / "tampered", evidence_manifest=tampered)
    with pytest.raises(ValidationError, match="missing from the manifest"):
        EvidenceManifest(
            id=content_id("invalid-manifest"),
            evidence=references,
            sets=(
                EvidenceSet(
                    id=content_id("invalid-set"),
                    count=1,
                    members=(content_id("not-present"),),
                ),
            ),
        )


def test_verifier_rejects_manifest_contract_identity_count_and_set_failures(
    tmp_path: Path,
) -> None:
    evidence = (EvidenceRef(id=content_id("manifest-item"), kind="observation"),)
    evidence_set = create_evidence_set(evidence)
    manifest = create_evidence_manifest(evidence, (evidence_set,))

    remote_ref = EvidenceManifestRef(
        id=manifest.id,
        uri="https://example.invalid/manifest.json",
        evidence_count=1,
        set_count=1,
    )
    remote_report = create_report(
        baseline_snapshot_id=content_id("remote-manifest-baseline"),
        candidate_snapshot_id=content_id("remote-manifest-candidate"),
        metrics=(),
        decision=MCRDecision(status=MCRStatus.PASS, allowed=True),
        evidence_manifest=remote_ref,
    )
    write_raw_bundle(tmp_path / "remote", remote_report)
    with pytest.raises(MCRVerificationError, match="remote evidence manifests"):
        verify_report_bundle(tmp_path / "remote")

    reference = EvidenceManifestRef(id=manifest.id, evidence_count=1, set_count=1)
    report = create_report(
        baseline_snapshot_id=content_id("manifest-baseline"),
        candidate_snapshot_id=content_id("manifest-candidate"),
        metrics=(),
        decision=MCRDecision(status=MCRStatus.PASS, allowed=True),
        evidence_manifest=reference,
    )
    malformed = tmp_path / "malformed-manifest"
    write_raw_bundle(malformed, report)
    (malformed / "evidence-manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(MCRVerificationError, match="manifest does not match its contract"):
        verify_report_bundle(malformed)

    wrong_identity = create_evidence_manifest(
        evidence,
        (evidence_set.model_copy(update={"id": content_id("wrong-set")}),),
    )
    wrong_reference = EvidenceManifestRef(id=wrong_identity.id, evidence_count=1, set_count=1)
    wrong_report = create_report(
        baseline_snapshot_id=content_id("wrong-set-baseline"),
        candidate_snapshot_id=content_id("wrong-set-candidate"),
        metrics=(),
        decision=MCRDecision(status=MCRStatus.PASS, allowed=True),
        evidence_manifest=wrong_reference,
    )
    write_raw_bundle(tmp_path / "wrong-set", wrong_report, manifest=wrong_identity)
    with pytest.raises(MCRVerificationError, match="set identity"):
        verify_report_bundle(tmp_path / "wrong-set")

    wrong_count_ref = reference.model_copy(update={"evidence_count": 2})
    wrong_count_report = create_report(
        baseline_snapshot_id=content_id("wrong-count-baseline"),
        candidate_snapshot_id=content_id("wrong-count-candidate"),
        metrics=(),
        decision=MCRDecision(status=MCRStatus.PASS, allowed=True),
        evidence_manifest=wrong_count_ref,
    )
    write_raw_bundle(tmp_path / "wrong-count", wrong_count_report, manifest=manifest)
    with pytest.raises(MCRVerificationError, match="counts do not match"):
        verify_report_bundle(tmp_path / "wrong-count")

    unknown_set = content_id("unknown-report-set")
    unknown_report = create_report(
        baseline_snapshot_id=content_id("unknown-set-baseline"),
        candidate_snapshot_id=content_id("unknown-set-candidate"),
        metrics=(
            MCRMetric(
                metric_id="accuracy",
                baseline_value=1,
                candidate_value=1,
                delta=0,
                sample_size=1,
                evidence_set_id=unknown_set,
            ),
        ),
        decision=MCRDecision(status=MCRStatus.PASS, allowed=True),
        evidence_manifest=reference,
    )
    write_raw_bundle(tmp_path / "unknown-set", unknown_report, manifest=manifest)
    with pytest.raises(MCRVerificationError, match="unknown evidence set"):
        verify_report_bundle(tmp_path / "unknown-set")


def test_report_contracts_reject_duplicate_and_incoherent_provenance() -> None:
    evidence = EvidenceRef(id=content_id("duplicate-evidence"), kind="observation")
    evidence_set = create_evidence_set((evidence,))
    with pytest.raises(ValueError, match="at least one"):
        create_evidence_set(())
    with pytest.raises(ValidationError, match="unique ids"):
        EvidenceManifest(
            id=content_id("duplicate-manifest-evidence"),
            evidence=(evidence, evidence),
            sets=(evidence_set,),
        )
    with pytest.raises(ValidationError, match="unique ids"):
        EvidenceManifest(
            id=content_id("duplicate-manifest-sets"),
            evidence=(evidence,),
            sets=(evidence_set, evidence_set),
        )
    with pytest.raises(ValidationError, match="cannot exceed"):
        MCRExecution(
            role="baseline",
            executor_id="local",
            executor_version="1",
            config_fingerprint="5" * 64,
            requested_cases=1,
            returned_observations=2,
        )
    execution = MCRExecution(
        role="baseline",
        executor_id="local",
        executor_version="1",
        config_fingerprint="6" * 64,
        requested_cases=1,
        returned_observations=1,
    )
    with pytest.raises(ValidationError, match="timezone-aware"):
        sample_report().model_copy(update={"created_at": datetime(2026, 8, 29)}).model_validate(
            sample_report().model_dump() | {"created_at": datetime(2026, 8, 29)}
        )
    with pytest.raises(ValidationError, match="roles must be unique"):
        ModelChangeReport.model_validate(
            sample_report().model_dump() | {"executions": [execution, execution]}
        )
    with pytest.raises(ValidationError, match="require an evidence manifest"):
        ModelChangeReport.model_validate(
            sample_report().model_dump()
            | {
                "metrics": [
                    sample_report()
                    .metrics[0]
                    .model_copy(update={"evidence_set_id": content_id("dangling")})
                ]
            }
        )


def test_bundle_writer_rejects_mismatched_plan_and_manifest_links(tmp_path: Path) -> None:
    plan = sample_plan()
    report = sample_report()
    with pytest.raises(ValueError, match="release plan identity"):
        write_report_bundle(report, tmp_path / "plan", release_plan=plan)

    evidence = (EvidenceRef(id=content_id("writer-evidence"), kind="observation"),)
    evidence_set = create_evidence_set(evidence)
    manifest = create_evidence_manifest(evidence, (evidence_set,))
    with pytest.raises(ValueError, match="must be provided together"):
        write_report_bundle(report, tmp_path / "manifest-only", evidence_manifest=manifest)

    reference = EvidenceManifestRef(id=manifest.id, evidence_count=1, set_count=1)
    linked = create_report(
        baseline_snapshot_id=content_id("writer-baseline"),
        candidate_snapshot_id=content_id("writer-candidate"),
        metrics=(
            MCRMetric(
                metric_id="accuracy",
                baseline_value=1,
                candidate_value=1,
                delta=0,
                sample_size=1,
                evidence_set_id=evidence_set.id,
            ),
        ),
        decision=MCRDecision(status=MCRStatus.PASS, allowed=True),
        evidence_manifest=reference,
    )
    wrong_reference = linked.model_copy(
        update={"evidence_manifest": reference.model_copy(update={"evidence_count": 2})}
    )
    wrong_reference = create_report(
        baseline_snapshot_id=wrong_reference.baseline_snapshot_id,
        candidate_snapshot_id=wrong_reference.candidate_snapshot_id,
        metrics=wrong_reference.metrics,
        decision=wrong_reference.decision,
        evidence_manifest=wrong_reference.evidence_manifest,
    )
    with pytest.raises(ValueError, match="MCR reference"):
        write_report_bundle(
            wrong_reference, tmp_path / "wrong-reference", evidence_manifest=manifest
        )


def test_ci_renderers_surface_block_as_failure_and_error_level() -> None:
    report = sample_report().model_copy(
        update={
            "decision": MCRDecision(
                status=MCRStatus.BLOCK,
                allowed=False,
                findings=(
                    MCRFinding(
                        rule_id="rare-quality",
                        metric_id="rare_class_recall",
                        status=MCRStatus.BLOCK,
                        message="rare slice exceeded margin",
                    ),
                ),
            )
        }
    )
    junit = ElementTree.fromstring(render_junit(report))
    assert junit.attrib["failures"] == "1"
    assert junit.find("./testcase/failure") is not None
    sarif = json.loads(render_sarif(report))
    assert sarif["version"] == "2.1.0"
    assert sarif["runs"][0]["results"][0]["level"] == "error"


def test_external_producer_conformance_fixtures_are_current_and_valid() -> None:
    root = Path(__file__).parents[1]
    subprocess.run(
        [
            sys.executable,
            str(root / "examples" / "mcr_conformance" / "generate_fixtures.py"),
            "--check",
        ],
        check=True,
        timeout=30,
    )
    for expected in ("PASS", "WARN", "BLOCK", "ERROR"):
        fixture = root / "examples" / "mcr_conformance" / expected.lower()
        result = verify_report_bundle(fixture)
        assert result.valid is True
        assert result.decision_status == expected


def test_independent_full_bundle_is_current_complete_and_valid() -> None:
    root = Path(__file__).parents[1]
    producer = root / "examples" / "independent_producer" / "generate_bundle.py"
    source = producer.read_text(encoding="utf-8")
    assert "from merriv" not in source
    assert "import merriv" not in source
    subprocess.run(
        [sys.executable, str(producer), "--check"],
        check=True,
        timeout=30,
    )

    result = verify_report_bundle(root / "examples" / "mcr_conformance" / "full")
    assert result.valid is True
    assert result.integrity_valid is True
    assert result.bundle_verification_complete is True
    assert result.decision_status == "BLOCK"
    assert result.evidence_body_coverage.verified_structured == 2
    assert result.evidence_body_coverage.unavailable == 2
    assert result.evidence_body_coverage.coverage == 0.5
    assert result.metric_recomputable is False
    assert {
        "manifest-id",
        "evidence-set-ids",
        "release-plan-id",
        "supplemental-id:artifact-diff",
        "supplemental-id:numerical-diff",
    }.issubset(result.checks)


@pytest.mark.parametrize(
    ("allowed", "junit_failures", "sarif_level"),
    [(False, "1", "error"), (True, "0", "warning")],
)
def test_warn_ci_rendering_respects_release_disposition(
    allowed: bool, junit_failures: str, sarif_level: str
) -> None:
    report = sample_report().model_copy(
        update={
            "decision": MCRDecision(
                status=MCRStatus.WARN,
                allowed=allowed,
                findings=(
                    MCRFinding(
                        rule_id="insufficient-pairs",
                        metric_id="rare_class_recall",
                        status=MCRStatus.WARN,
                        message="insufficient evidence",
                    ),
                ),
            )
        }
    )
    junit = ElementTree.fromstring(render_junit(report))
    sarif = json.loads(render_sarif(report))
    assert junit.attrib["failures"] == junit_failures
    assert sarif["runs"][0]["results"][0]["level"] == sarif_level
    properties = sarif["runs"][0]["results"][0]["properties"]
    assert properties["evaluationPolicySatisfied"] is allowed
    assert properties["deploymentAuthorization"] == "not-evaluated"
