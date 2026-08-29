"""Standalone integrity verification for portable MCR report bundles."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import Field, ValidationError

from m2riv.artifacts import ArtifactDiff, NumericalDiff
from m2riv.core.identity import fingerprint, has_link_like_component, read_verified_file
from m2riv.core.models import ContentId, Contract, EvidenceRef
from m2riv.evidence import BackendComparisonEvidence
from m2riv.io.json import StrictJSONError, parse_strict_json
from m2riv.planning import CompiledReleasePlan
from m2riv.reports.models import (
    EvidenceManifest,
    MCRStatus,
    ModelChangeReport,
    create_evidence_manifest,
    create_evidence_set,
    create_report,
)

MAX_BUNDLE_JSON_BYTES = 64 * 1024 * 1024
MAX_JSON_FILE_BYTES = 16 * 1024 * 1024


class MCRVerificationError(ValueError):
    """An MCR bundle is malformed, incomplete, or fails content verification."""


class MCRVerification(Contract):
    """Machine-readable result from verifying one MCR bundle."""

    schema_version: Literal["1.2.0"] = "1.2.0"
    valid: bool = True
    integrity_valid: bool = True
    authenticity_verified: bool = False
    trust_scope: Literal["self-consistency-only"] = "self-consistency-only"
    verification_complete: bool
    verification_scope: Literal["report-and-local-bundle"] = "report-and-local-bundle"
    verified_evidence_count: int = Field(ge=0)
    unverified_evidence_count: int = Field(ge=0)
    report_id: ContentId
    run_id: ContentId
    decision_status: MCRStatus
    checks: tuple[str, ...] = Field(min_length=1, max_length=128)
    warnings: tuple[str, ...] = Field(default=(), max_length=128)


def _read_json(path: Path, *, budget: list[int]) -> Any:
    try:
        encoded = read_verified_file(path, max_bytes=MAX_JSON_FILE_BYTES)
    except ValueError as error:
        if "exceeds" in str(error):
            raise MCRVerificationError(
                f"bundle file exceeds JSON size limit: {path.name}"
            ) from error
        raise MCRVerificationError(f"required bundle file is unavailable: {path.name}") from error
    except OSError as error:
        raise MCRVerificationError(f"required bundle file is unavailable: {path.name}") from error
    budget[0] += len(encoded)
    if budget[0] > MAX_BUNDLE_JSON_BYTES:
        raise MCRVerificationError("bundle exceeds total JSON size limit")
    try:
        return parse_strict_json(encoded)
    except StrictJSONError as error:
        raise MCRVerificationError(f"bundle file is not valid UTF-8 JSON: {path.name}") from error


def _local_reference(root: Path, uri: str) -> Path | None:
    if "://" in uri:
        return None
    normalized = uri.replace("\\", "/")
    relative = PurePosixPath(normalized)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(
            part in {"", ".", ".."}
            or ":" in part
            or any(not character.isprintable() for character in part)
            for part in relative.parts
        )
    ):
        raise MCRVerificationError("bundle reference must be a safe relative path")
    cursor = root
    paths = [root]
    for part in relative.parts:
        cursor /= part
        paths.append(cursor)
    if any(has_link_like_component(path) for path in paths):
        raise MCRVerificationError("bundle references must not use symbolic links")
    candidate = cursor.resolve()
    resolved_root = root.resolve()
    if not candidate.is_relative_to(resolved_root):
        raise MCRVerificationError("bundle reference escapes the report directory")
    return candidate


def _expected_embedded_id(reference: EvidenceRef, payload: Any) -> None:
    if not isinstance(payload, dict) or payload.get("id") != reference.id:
        raise MCRVerificationError(
            f"supplemental evidence identity does not match its reference: {reference.kind}"
        )


def _verify_supplemental_identity(reference: EvidenceRef, payload: Any) -> bool:
    _expected_embedded_id(reference, payload)
    try:
        if reference.kind == "artifact-diff":
            artifact_diff = ArtifactDiff.model_validate(payload)
            expected = fingerprint(
                artifact_diff.model_dump(mode="python", exclude={"schema_version", "id"}),
                namespace="artifact-diff",
            )
            if artifact_diff.id != f"m2riv:sha256:{expected}":
                raise MCRVerificationError("artifact diff identity does not match its contents")
            return True
        if reference.kind == "numerical-diff":
            numerical_diff = NumericalDiff.model_validate(payload)
            expected = fingerprint(
                numerical_diff.model_dump(mode="python", exclude={"schema_version", "id"}),
                namespace="onnx-numerical-diff",
            )
            if numerical_diff.id != f"m2riv:sha256:{expected}":
                raise MCRVerificationError("numerical diff identity does not match its contents")
            return True
        if reference.kind == "backend-comparison":
            backend_comparison = BackendComparisonEvidence.model_validate(payload)
            expected = fingerprint(
                backend_comparison.model_dump(mode="python", exclude={"schema_version", "id"}),
                namespace="backend-comparison-evidence",
            )
            if backend_comparison.id != f"m2riv:sha256:{expected}":
                raise MCRVerificationError(
                    "backend comparison identity does not match its contents"
                )
            return True
    except ValidationError as error:
        raise MCRVerificationError(
            f"supplemental evidence does not match its contract: {reference.kind}"
        ) from error
    return False


def _verify_report_identity(report: ModelChangeReport) -> None:
    canonical = create_report(
        baseline_snapshot_id=report.baseline_snapshot_id,
        candidate_snapshot_id=report.candidate_snapshot_id,
        release_plan_id=report.release_plan_id,
        executions=report.executions,
        metrics=report.metrics,
        decision=report.decision,
        evidence_manifest=report.evidence_manifest,
        evidence=report.evidence,
        limitations=report.limitations,
        created_at=report.created_at,
    )
    if canonical.id != report.id or canonical.run_id != report.run_id:
        raise MCRVerificationError("MCR report or run identity does not match its contents")


def _verify_release_plan(root: Path, report: ModelChangeReport, budget: list[int]) -> bool:
    if report.release_plan_id is None:
        return False
    path = root / "release-plan.json"
    if not path.exists():
        return False
    try:
        plan = CompiledReleasePlan.model_validate(_read_json(path, budget=budget))
    except ValidationError as error:
        raise MCRVerificationError("release plan does not match its contract") from error
    expected = fingerprint(plan.model_dump(mode="python", exclude={"id"}), namespace="release-plan")
    if plan.id != report.release_plan_id or plan.id != f"m2riv:sha256:{expected}":
        raise MCRVerificationError("release plan identity does not match the MCR")
    return True


def _verify_manifest(
    root: Path, report: ModelChangeReport, budget: list[int]
) -> EvidenceManifest | None:
    reference = report.evidence_manifest
    if reference is None:
        return None
    path = _local_reference(root, reference.uri)
    if path is None:
        raise MCRVerificationError("remote evidence manifests are not verified")
    try:
        manifest = EvidenceManifest.model_validate(_read_json(path, budget=budget))
    except ValidationError as error:
        raise MCRVerificationError("evidence manifest does not match its contract") from error
    canonical = create_evidence_manifest(manifest.evidence, manifest.sets)
    if canonical.id != manifest.id or reference.id != manifest.id:
        raise MCRVerificationError("evidence manifest identity does not match its contents")
    if reference.evidence_count != len(manifest.evidence) or reference.set_count != len(
        manifest.sets
    ):
        raise MCRVerificationError("evidence manifest counts do not match the MCR")
    for evidence_set in manifest.sets:
        members = {item.id: item for item in manifest.evidence}
        canonical_set = create_evidence_set(tuple(members[item] for item in evidence_set.members))
        if canonical_set.id != evidence_set.id or canonical_set.count != evidence_set.count:
            raise MCRVerificationError("evidence set identity does not match its members")
    available_sets = {item.id for item in manifest.sets}
    referenced_sets = {
        metric.evidence_set_id for metric in report.metrics if metric.evidence_set_id is not None
    } | {
        finding.evidence_set_id
        for finding in report.decision.findings
        if finding.evidence_set_id is not None
    }
    if not referenced_sets.issubset(available_sets):
        raise MCRVerificationError("MCR references an unknown evidence set")
    return manifest


def verify_report_bundle(
    source: str | Path,
    *,
    require_complete: bool = False,
) -> MCRVerification:
    """Verify report self-consistency without claiming producer authenticity."""
    requested = Path(source)
    report_path = requested / "m2riv-report.json" if requested.is_dir() else requested
    root = report_path.parent
    budget = [0]
    try:
        report = ModelChangeReport.model_validate(_read_json(report_path, budget=budget))
    except ValidationError as error:
        raise MCRVerificationError("MCR report does not match its contract") from error
    _verify_report_identity(report)
    checks = ["report-contract", "report-id", "run-id"]
    warnings: list[str] = []
    verified_evidence_count = 0
    unverified_evidence_count = 0
    manifest = _verify_manifest(root, report, budget)
    if manifest is not None:
        checks.extend(("manifest-id", "evidence-set-ids", "evidence-set-references"))
    if _verify_release_plan(root, report, budget):
        checks.append("release-plan-id")
    elif report.release_plan_id is not None:
        warnings.append("release-plan.json is not present; its referenced id was not rehashed")
    for reference in report.evidence:
        if reference.redacted or reference.uri is None:
            warnings.append(f"{reference.kind} evidence body is unavailable")
            unverified_evidence_count += 1
            continue
        path = _local_reference(root, reference.uri)
        if path is None:
            warnings.append(f"remote {reference.kind} evidence was not fetched")
            unverified_evidence_count += 1
            continue
        payload = _read_json(path, budget=budget)
        if _verify_supplemental_identity(reference, payload):
            checks.append(f"supplemental-id:{reference.kind}")
            verified_evidence_count += 1
        else:
            warnings.append(
                f"{reference.kind} embeds the referenced id but has no built-in rehasher"
            )
            unverified_evidence_count += 1
    if require_complete and warnings:
        raise MCRVerificationError(
            f"strict verification requires all linked evidence; found {len(warnings)} warning(s)"
        )
    return MCRVerification(
        verification_complete=not warnings,
        verified_evidence_count=verified_evidence_count,
        unverified_evidence_count=unverified_evidence_count,
        report_id=report.id,
        run_id=report.run_id,
        decision_status=report.decision.status,
        checks=tuple(dict.fromkeys(checks)),
        warnings=tuple(warnings),
    )
