"""Producer- and consumer-neutral MCR conformance contracts and checks."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from m2riv.core.identity import fingerprint, read_verified_file
from m2riv.core.models import (
    ContentId,
    Contract,
    RuntimeProfile,
    SafePluginName,
    SafePluginVersion,
)
from m2riv.io.json import StrictJSONError, parse_strict_json
from m2riv.reports.models import (
    MCRDecision,
    MCRExecution,
    MCRFinding,
    MCRMetric,
    MCRStatus,
    ModelChangeReport,
    create_report,
)
from m2riv.reports.verify import MCRVerificationError, verify_report_bundle

ConformanceProfileName = Literal["pass", "warn", "block", "error"]
_EXPECTED_STATUSES: tuple[tuple[ConformanceProfileName, MCRStatus], ...] = (
    ("pass", MCRStatus.PASS),
    ("warn", MCRStatus.WARN),
    ("block", MCRStatus.BLOCK),
    ("error", MCRStatus.ERROR),
)
_NEGATIVE_PROFILES = (
    "tampered-id",
    "missing-evidence",
    "unknown-version",
    "decision-mismatch",
)
MAX_RECEIPT_BYTES = 1024 * 1024


class MCRConformanceError(ValueError):
    """A producer or consumer failed the normative MCR conformance profile."""


class ConformanceProfile(Contract):
    """One normative four-state interoperability observation."""

    profile: ConformanceProfileName
    report_id: ContentId
    evidence_id: ContentId
    decision_status: MCRStatus
    release_authorized: bool

    @model_validator(mode="after")
    def authorization_matches_status(self) -> ConformanceProfile:
        expected = self.decision_status is MCRStatus.PASS
        if self.release_authorized is not expected:
            raise ValueError("only PASS may be release-authorized by the conformance profile")
        return self


class ConsumerConformanceReceipt(Contract):
    """Portable receipt emitted by an MCR consumer over the normative fixtures."""

    schema_version: Literal["0.2.0"] = "0.2.0"
    id: ContentId
    implementation_name: SafePluginName
    implementation_version: SafePluginVersion
    profiles: tuple[ConformanceProfile, ...] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def profiles_are_unique_and_complete(self) -> ConsumerConformanceReceipt:
        names = tuple(profile.profile for profile in self.profiles)
        expected = {"pass", "warn", "block", "error"}
        if len(names) != len(set(names)) or set(names) != expected:
            raise ValueError("consumer receipt must contain PASS, WARN, BLOCK, and ERROR once")
        return self


class MCRConformanceResult(Contract):
    """Machine-readable outcome for one producer or consumer conformance run."""

    schema_version: Literal["0.2.0"] = "0.2.0"
    id: ContentId
    subject: Literal["producer", "consumer"]
    conformant: Literal[True] = True
    implementation_name: SafePluginName | None = None
    implementation_version: SafePluginVersion | None = None
    profiles: tuple[ConformanceProfile, ...] = Field(min_length=4, max_length=4)
    checks: tuple[str, ...] = Field(min_length=1, max_length=64)
    warnings: tuple[str, ...] = Field(default=(), max_length=64)


def _result(
    *,
    subject: Literal["producer", "consumer"],
    profiles: tuple[ConformanceProfile, ...],
    checks: tuple[str, ...],
    implementation_name: str | None = None,
    implementation_version: str | None = None,
    warnings: tuple[str, ...] = (),
) -> MCRConformanceResult:
    payload = {
        "schema_version": "0.2.0",
        "subject": subject,
        "conformant": True,
        "implementation_name": implementation_name,
        "implementation_version": implementation_version,
        "profiles": profiles,
        "checks": checks,
        "warnings": warnings,
    }
    identifier = fingerprint(payload, namespace="mcr-conformance-result")
    return MCRConformanceResult(
        id=f"mcr:sha256:{identifier}",
        subject=subject,
        conformant=True,
        implementation_name=implementation_name,
        implementation_version=implementation_version,
        profiles=profiles,
        checks=checks,
        warnings=warnings,
    )


def create_consumer_receipt(
    *,
    implementation_name: str,
    implementation_version: str,
    profiles: tuple[ConformanceProfile, ...],
) -> ConsumerConformanceReceipt:
    """Create a deterministic receipt that an independent consumer can reproduce."""
    payload = {
        "schema_version": "0.2.0",
        "implementation_name": implementation_name,
        "implementation_version": implementation_version,
        "profiles": profiles,
    }
    identifier = fingerprint(payload, namespace="mcr-consumer-receipt")
    return ConsumerConformanceReceipt(
        id=f"mcr:sha256:{identifier}",
        implementation_name=implementation_name,
        implementation_version=implementation_version,
        profiles=profiles,
    )


def _fixture_content_id(label: str) -> ContentId:
    return f"mcr:sha256:{fingerprint(label, namespace='external-fixture')}"


def normative_profile_report(status: MCRStatus) -> ModelChangeReport:
    """Return the fixed-input/fixed-output normative MCR test vector."""
    allowed = status is MCRStatus.PASS
    returned = 0 if status is MCRStatus.ERROR else 10
    execution = MCRExecution(
        role="candidate",
        executor_id="example.external-producer",
        executor_version="1.0",
        config_fingerprint=fingerprint("external", namespace="fixture-config"),
        runtime_profile=RuntimeProfile(
            framework="fixture-runtime",
            framework_version="1.0",
            device="cpu",
            operating_system="portable-fixture",
            architecture="generic",
            python_version="3.11+",
        ),
        capabilities=frozenset({"paired-observations"}),
        requested_cases=10,
        returned_observations=returned,
    )
    metrics: tuple[MCRMetric, ...]
    metric_id: str | None
    if status is MCRStatus.ERROR:
        metrics = ()
        metric_id = None
    else:
        delta = {MCRStatus.PASS: 0.0, MCRStatus.WARN: -0.02, MCRStatus.BLOCK: -0.2}[status]
        metrics = (
            MCRMetric(
                metric_id="accuracy",
                baseline_value=0.9,
                candidate_value=0.9 + delta,
                delta=delta,
                sample_size=10,
            ),
        )
        metric_id = "accuracy"
    finding = MCRFinding(
        rule_id="accuracy-floor" if metric_id else "executor-completeness",
        status=status,
        metric_id=metric_id,
        message=f"external producer fixture: {status.value}",
    )
    return create_report(
        baseline_snapshot_id=_fixture_content_id("baseline"),
        candidate_snapshot_id=_fixture_content_id(f"candidate-{status.value.lower()}"),
        executions=(execution,),
        metrics=metrics,
        decision=MCRDecision(status=status, allowed=allowed, findings=(finding,)),
        limitations=("Minimal external-producer conformance fixture; no model was run.",),
        created_at=datetime(2026, 8, 29, tzinfo=UTC),
    )


def _load_profile_report(path: Path) -> ModelChangeReport:
    try:
        payload = parse_strict_json(read_verified_file(path, max_bytes=MAX_RECEIPT_BYTES))
        return ModelChangeReport.model_validate(payload)
    except (OSError, ValueError, StrictJSONError, ValidationError) as error:
        raise MCRConformanceError("normative producer report is unavailable or invalid") from error


def verify_producer_conformance(source: str | Path) -> MCRConformanceResult:
    """Verify fixed-output four-state and must-reject MCR test vectors."""
    root = Path(source)
    profiles: list[ConformanceProfile] = []
    warnings: list[str] = []
    for profile_name, expected_status in _EXPECTED_STATUSES:
        bundle = root / profile_name
        if not bundle.is_dir():
            raise MCRConformanceError(
                f"producer suite is missing profile directory: {profile_name}"
            )
        try:
            verification = verify_report_bundle(bundle, require_complete=True)
        except (OSError, MCRVerificationError) as error:
            raise MCRConformanceError(
                f"producer {profile_name} profile failed MCR verification: {error}"
            ) from error
        if verification.decision_status is not expected_status:
            raise MCRConformanceError(
                f"producer {profile_name} profile reported {verification.decision_status.value}"
            )
        observed_report = _load_profile_report(bundle / "mcr-report.json")
        expected_report = normative_profile_report(expected_status)
        if observed_report != expected_report:
            raise MCRConformanceError(
                f"producer {profile_name} output does not match the normative semantic vector"
            )
        profiles.append(
            ConformanceProfile(
                profile=profile_name,
                report_id=verification.report_id,
                evidence_id=verification.evidence_id,
                decision_status=verification.decision_status,
                release_authorized=verification.decision_status is MCRStatus.PASS,
            )
        )
        warnings.extend(verification.warnings)
    for negative_name in _NEGATIVE_PROFILES:
        negative = root / "negative" / negative_name
        if not negative.is_dir():
            raise MCRConformanceError(
                f"producer suite is missing negative profile directory: {negative_name}"
            )
        try:
            verify_report_bundle(negative, require_complete=True)
        except (OSError, MCRVerificationError):
            continue
        raise MCRConformanceError(f"negative profile was incorrectly accepted: {negative_name}")
    return _result(
        subject="producer",
        profiles=tuple(profiles),
        checks=(
            "mcr-contracts",
            "content-identities",
            "fixed-semantic-and-content-id-vectors",
            "pass-warn-block-error-preserved",
            "negative-vectors-rejected",
            "complete-local-bundle",
        ),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _read_receipt(path: Path) -> ConsumerConformanceReceipt:
    try:
        payload = parse_strict_json(read_verified_file(path, max_bytes=MAX_RECEIPT_BYTES))
        return ConsumerConformanceReceipt.model_validate(payload)
    except (OSError, ValueError, StrictJSONError, ValidationError) as error:
        raise MCRConformanceError("consumer receipt is unavailable or invalid") from error


def verify_consumer_conformance(
    receipt_path: str | Path,
    *,
    fixtures: str | Path,
) -> MCRConformanceResult:
    """Verify a consumer receipt against the normative producer fixtures."""
    receipt = _read_receipt(Path(receipt_path))
    canonical = create_consumer_receipt(
        implementation_name=receipt.implementation_name,
        implementation_version=receipt.implementation_version,
        profiles=receipt.profiles,
    )
    if receipt.id != canonical.id:
        raise MCRConformanceError("consumer receipt identity does not match its contents")

    expected = verify_producer_conformance(fixtures)
    expected_by_name = {profile.profile: profile for profile in expected.profiles}
    for observed in receipt.profiles:
        reference = expected_by_name[observed.profile]
        if observed != reference:
            raise MCRConformanceError(
                f"consumer did not preserve the {observed.profile.upper()} fixture semantics"
            )
    return _result(
        subject="consumer",
        implementation_name=receipt.implementation_name,
        implementation_version=receipt.implementation_version,
        profiles=receipt.profiles,
        checks=(
            "receipt-id",
            "report-and-evidence-ids",
            "pass-warn-block-error-preserved",
            "warn-block-error-fail-closed",
        ),
    )
