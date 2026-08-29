from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

import pytest
from pydantic import ValidationError

from m2riv.core.identity import fingerprint
from m2riv.core.models import EvidenceRef
from m2riv.reports import (
    EvidenceManifest,
    EvidenceManifestRef,
    EvidenceSet,
    MCRDecision,
    MCRFinding,
    MCRMetric,
    MCRStatus,
    ModelChangeReport,
    create_evidence_manifest,
    create_evidence_set,
    create_report,
    render_json,
    render_junit,
    render_markdown,
    render_sarif,
    write_report_bundle,
)


def content_id(label: str) -> str:
    return f"m2riv:sha256:{fingerprint(label, namespace='report-test')}"


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


def test_report_round_trip_and_stable_identity() -> None:
    report = sample_report()
    assert report.schema_version == "1.2.0"
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
            first.metrics[1].model_copy(
                update={"baseline_value": 1.5, "candidate_value": 2.5}
            ),
        ),
        decision=first.decision,
        created_at=datetime(2026, 8, 29, tzinfo=UTC),
    )

    assert first.id == second.id
    assert first.run_id != second.run_id


def test_markdown_surfaces_decision_and_slice() -> None:
    markdown = render_markdown(sample_report())
    assert "**Decision: BLOCK**" in markdown
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
    for status in (MCRStatus.ERROR, MCRStatus.BLOCK):
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
    assert bundle.json_path.name == "m2riv-report.json"
    assert bundle.markdown_path.name == "summary.md"
    assert bundle.junit_path.name == "junit.xml"
    assert bundle.sarif_path.name == "results.sarif"
    assert ModelChangeReport.model_validate_json(bundle.json_path.read_text("utf-8")) == report
    assert "Decision: BLOCK" in bundle.markdown_path.read_text("utf-8")
    with pytest.raises(ValueError, match="MCR identity"):
        write_report_bundle(
            report.model_copy(update={"run_id": content_id("tampered-run")}),
            tmp_path / "tampered-report",
        )


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
    assert EvidenceManifest.model_validate_json(
        bundle.evidence_manifest_path.read_text("utf-8")
    ) == manifest
    assert "evidence-manifest.json" in bundle.markdown_path.read_text("utf-8")

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
    assert sarif["runs"][0]["results"][0]["properties"]["releaseAllowed"] is allowed
