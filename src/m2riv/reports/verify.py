"""Standalone integrity verification for portable MCR report bundles."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import Field, FiniteFloat, ValidationError, model_validator

from m2riv.artifacts import ArtifactDiff, NumericalDiff
from m2riv.core.identity import (
    fingerprint,
    has_link_like_component,
    hash_artifact,
    observation_content_id,
    read_verified_file,
)
from m2riv.core.models import ContentId, Contract, EvidenceRef, Observation, RetentionMode
from m2riv.evidence import (
    BackendComparisonEvidence,
    BuildProvenanceEvidence,
    SnapshotArtifactManifest,
    ToolNativeEvidence,
    create_build_provenance_evidence,
    create_snapshot_artifact_manifest,
)
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


class EvidenceBodyCoverage(Contract):
    """Mutually exclusive coverage classes for every declared evidence body."""

    declared: int = Field(ge=0)
    verified_structured: int = Field(ge=0)
    verified_opaque: int = Field(ge=0)
    unavailable: int = Field(ge=0)
    remote: int = Field(ge=0)
    redacted: int = Field(ge=0)
    unrecognized_local: int = Field(ge=0)
    coverage: FiniteFloat = Field(ge=0, le=1)

    @model_validator(mode="after")
    def categories_cover_declarations(self) -> EvidenceBodyCoverage:
        classified = (
            self.verified_structured
            + self.verified_opaque
            + self.unavailable
            + self.remote
            + self.redacted
            + self.unrecognized_local
        )
        if classified != self.declared:
            raise ValueError("evidence coverage categories must equal declared evidence")
        expected = (
            (self.verified_structured + self.verified_opaque) / self.declared
            if self.declared
            else 1.0
        )
        if abs(self.coverage - expected) > 1e-12:
            raise ValueError("evidence body coverage ratio does not match counts")
        return self


class MCRVerification(Contract):
    """Machine-readable result from verifying one MCR bundle."""

    schema_version: Literal["0.2.0"] = "0.2.0"
    valid: bool = True
    integrity_valid: bool = True
    authenticity_verified: bool = False
    trust_scope: Literal["self-consistency-only"] = "self-consistency-only"
    bundle_verification_complete: bool
    verification_scope: Literal["report-and-local-bundle"] = "report-and-local-bundle"
    bundle_component_count: int = Field(ge=1)
    verified_bundle_component_count: int = Field(ge=1)
    evidence_body_coverage: EvidenceBodyCoverage
    metric_recomputable: bool
    observation_bodies_verified: bool
    report_id: ContentId
    evidence_id: ContentId
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


def _verify_file_binding(root: Path, uri: str, expected_digest: str, expected_size: int) -> None:
    path = _local_reference(root, uri)
    if path is None:
        raise MCRVerificationError("bound evidence files must be local bundle paths")
    try:
        actual = hash_artifact(path)
    except (OSError, ValueError) as error:
        raise MCRVerificationError("bound evidence file is unavailable or unsafe") from error
    if (
        actual.file_count != 1
        or actual.digest != expected_digest
        or actual.size_bytes != expected_size
    ):
        raise MCRVerificationError("bound evidence file digest or size does not match")


def _verify_snapshot_identity(manifest: SnapshotArtifactManifest) -> None:
    snapshot = manifest.snapshot
    expected = fingerprint(
        {
            "artifacts": [
                item.model_dump(exclude={"logical_name"})
                for item in snapshot.artifact_hashes
            ],
            "config_fingerprint": snapshot.config_fingerprint,
        },
        namespace="model-snapshot",
    )
    if snapshot.id != f"mcr:sha256:{expected}":
        raise MCRVerificationError("snapshot identity does not match its artifact/config digest")


def _verify_supplemental_identity(
    reference: EvidenceRef,
    payload: Any,
    *,
    root: Path,
) -> Literal["structured", "opaque"] | None:
    _expected_embedded_id(reference, payload)
    try:
        if reference.kind == "artifact-diff":
            artifact_diff = ArtifactDiff.model_validate(payload)
            expected = fingerprint(
                artifact_diff.model_dump(mode="python", exclude={"schema_version", "id"}),
                namespace="artifact-diff",
            )
            if artifact_diff.id != f"mcr:sha256:{expected}":
                raise MCRVerificationError("artifact diff identity does not match its contents")
            return "structured"
        if reference.kind == "numerical-diff":
            numerical_diff = NumericalDiff.model_validate(payload)
            expected = fingerprint(
                numerical_diff.model_dump(mode="python", exclude={"schema_version", "id"}),
                namespace="onnx-numerical-diff",
            )
            if numerical_diff.id != f"mcr:sha256:{expected}":
                raise MCRVerificationError("numerical diff identity does not match its contents")
            return "structured"
        if reference.kind == "backend-comparison":
            backend_comparison = BackendComparisonEvidence.model_validate(payload)
            expected = fingerprint(
                backend_comparison.model_dump(mode="python", exclude={"schema_version", "id"}),
                namespace="backend-comparison-evidence",
            )
            if backend_comparison.id != f"mcr:sha256:{expected}":
                raise MCRVerificationError(
                    "backend comparison identity does not match its contents"
                )
            return "structured"
        if reference.kind == "observation":
            observation = Observation.model_validate(payload)
            if observation.retention is RetentionMode.FULL:
                output_digest = fingerprint(observation.output, namespace="observation-output")
                if output_digest != observation.output_digest:
                    raise MCRVerificationError("observation output digest does not match its body")
            expected_id = observation_content_id(
                snapshot_id=observation.snapshot_id,
                case_id=observation.case_id,
                seed=observation.seed,
                output_digest=observation.output_digest,
                retention=observation.retention,
            )
            if observation.id != expected_id:
                raise MCRVerificationError("observation identity does not match its contents")
            return "structured"
        if reference.kind == "tool-native-evidence":
            native = ToolNativeEvidence.model_validate(payload)
            expected = fingerprint(
                {
                    "producer_name": native.producer_name,
                    "producer_version": native.producer_version,
                    "media_type": native.media_type,
                    "purpose": native.purpose,
                    "body": native.body.model_dump(mode="python", exclude={"uri"}),
                    "exit_code": native.exit_code,
                    "runner_names": native.runner_names,
                    "limitations": native.limitations,
                },
                namespace="tool-native-evidence",
            )
            if native.id != f"mcr:sha256:{expected}":
                raise MCRVerificationError("tool-native evidence identity does not match")
            _verify_file_binding(
                root, native.body.uri, native.body.sha256, native.body.size_bytes
            )
            return "opaque"
        if reference.kind == "snapshot-artifact-manifest":
            snapshot_manifest = SnapshotArtifactManifest.model_validate(payload)
            canonical = create_snapshot_artifact_manifest(
                snapshot_manifest.snapshot, snapshot_manifest.artifacts
            )
            if canonical.id != snapshot_manifest.id:
                raise MCRVerificationError("snapshot manifest identity does not match")
            _verify_snapshot_identity(snapshot_manifest)
            for binding in snapshot_manifest.artifacts:
                _verify_file_binding(root, binding.uri, binding.sha256, binding.size_bytes)
            return "structured"
        if reference.kind == "build-provenance":
            provenance = BuildProvenanceEvidence.model_validate(payload)
            canonical_provenance = create_build_provenance_evidence(
                build_name=provenance.build_name,
                builder_name=provenance.builder_name,
                builder_version=provenance.builder_version,
                input_artifacts=provenance.input_artifacts,
                output_artifacts=provenance.output_artifacts,
                output_snapshot_id=provenance.output_snapshot_id,
                source_commit=provenance.source_commit,
                parameters=provenance.parameters,
                calibration_cohort_digest=provenance.calibration_cohort_digest,
                parent_build_id=provenance.parent_build_id,
                limitations=provenance.limitations,
            )
            if canonical_provenance.id != provenance.id:
                raise MCRVerificationError("build provenance identity does not match")
            return "structured"
    except ValidationError as error:
        raise MCRVerificationError(
            f"supplemental evidence does not match its contract: {reference.kind}"
        ) from error
    return None


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
    if (
        canonical.id != report.id
        or canonical.evidence_id != report.evidence_id
        or canonical.run_id != report.run_id
    ):
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
    if plan.id != report.release_plan_id or plan.id != f"mcr:sha256:{expected}":
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
    if requested.is_dir():
        report_path = requested / "mcr-report.json"
        legacy_path = requested / "m2riv-report.json"
        if not report_path.exists() and legacy_path.exists():
            raise MCRVerificationError(
                "legacy MCR 1.3 bundle detected; migrate it to the MCR 0.4 identity contract"
            )
    else:
        report_path = requested
    root = report_path.parent
    budget = [0]
    try:
        report_payload = _read_json(report_path, budget=budget)
        if (
            isinstance(report_payload, dict)
            and "schema_version" in report_payload
            and report_payload.get("schema_version") != "0.4.0"
        ):
            version = report_payload.get("schema_version", "missing")
            raise MCRVerificationError(
                f"unsupported MCR schema version {version!r}; this verifier supports 0.4.0"
            )
        report = ModelChangeReport.model_validate(report_payload)
    except ValidationError as error:
        raise MCRVerificationError("MCR report does not match its contract") from error
    _verify_report_identity(report)
    checks = ["report-contract", "evidence-id", "report-id", "run-id"]
    warnings: list[str] = []
    verified_structured = 0
    verified_opaque = 0
    unavailable = 0
    remote = 0
    redacted = 0
    unrecognized_local = 0
    verified_ids: set[ContentId] = set()
    verified_observation_ids: set[ContentId] = set()
    native_evidence: dict[ContentId, ToolNativeEvidence] = {}
    snapshot_manifests: dict[ContentId, SnapshotArtifactManifest] = {}
    build_provenance: dict[ContentId, BuildProvenanceEvidence] = {}
    backend_evidence: list[BackendComparisonEvidence] = []
    bundle_component_count = 1
    verified_bundle_component_count = 1
    manifest = _verify_manifest(root, report, budget)
    if manifest is not None:
        checks.extend(("manifest-id", "evidence-set-ids", "evidence-set-references"))
        bundle_component_count += 1
        verified_bundle_component_count += 1
    release_plan_verified = _verify_release_plan(root, report, budget)
    if release_plan_verified:
        checks.append("release-plan-id")
        bundle_component_count += 1
        verified_bundle_component_count += 1
    elif report.release_plan_id is not None:
        bundle_component_count += 1
        warnings.append("release-plan.json is not present; its referenced id was not rehashed")
    references: dict[ContentId, EvidenceRef] = {}
    for reference in (*(() if manifest is None else manifest.evidence), *report.evidence):
        previous = references.get(reference.id)
        if previous is not None and previous != reference:
            raise MCRVerificationError("one evidence id has conflicting references")
        references[reference.id] = reference
    for reference in references.values():
        if reference.redacted:
            redacted += 1
            continue
        if reference.uri is None:
            unavailable += 1
            continue
        path = _local_reference(root, reference.uri)
        if path is None:
            remote += 1
            continue
        bundle_component_count += 1
        payload = _read_json(path, budget=budget)
        verification_kind = _verify_supplemental_identity(reference, payload, root=root)
        if verification_kind == "structured":
            checks.append(f"supplemental-id:{reference.kind}")
            verified_structured += 1
            verified_bundle_component_count += 1
            verified_ids.add(reference.id)
            if reference.kind == "observation":
                verified_observation_ids.add(reference.id)
            if reference.kind == "backend-comparison":
                backend = BackendComparisonEvidence.model_validate(payload)
                backend_evidence.append(backend)
            if reference.kind == "snapshot-artifact-manifest":
                snapshot = SnapshotArtifactManifest.model_validate(payload)
                snapshot_manifests[snapshot.snapshot.id] = snapshot
            if reference.kind == "build-provenance":
                provenance = BuildProvenanceEvidence.model_validate(payload)
                build_provenance[provenance.id] = provenance
        elif verification_kind == "opaque":
            checks.append(f"opaque-body:{reference.kind}")
            verified_opaque += 1
            verified_bundle_component_count += 1
            verified_ids.add(reference.id)
            if reference.kind == "tool-native-evidence":
                native = ToolNativeEvidence.model_validate(payload)
                native_evidence[native.id] = native
        else:
            warnings.append(
                f"{reference.kind} embeds the referenced id but has no built-in rehasher"
            )
            unrecognized_local += 1
    for backend in backend_evidence:
        linked_native = native_evidence.get(backend.tool_native_evidence_id)
        if linked_native is None:
            raise MCRVerificationError(
                "backend comparison is not linked to verified tool-native evidence"
            )
        if (
            linked_native.producer_name != backend.comparator_name
            or linked_native.producer_version != backend.comparator_version
            or linked_native.exit_code != backend.comparator_exit_code
            or backend.baseline_runner not in linked_native.runner_names
            or backend.candidate_runner not in linked_native.runner_names
        ):
            raise MCRVerificationError(
                "backend comparison disagrees with its tool-native evidence"
            )
        if (
            backend.baseline_snapshot_id not in snapshot_manifests
            or backend.candidate_snapshot_id not in snapshot_manifests
        ):
            raise MCRVerificationError(
                "backend comparison snapshots are not bound to retained artifact bytes"
            )
    for provenance in build_provenance.values():
        snapshot_manifest = snapshot_manifests.get(provenance.output_snapshot_id)
        if snapshot_manifest is None:
            raise MCRVerificationError(
                "build provenance output snapshot is not bound to retained artifact bytes"
            )
        expected_outputs = sorted(
            snapshot_manifest.snapshot.artifact_hashes,
            key=lambda item: (item.digest, item.size_bytes, item.logical_name or ""),
        )
        declared_outputs = sorted(
            provenance.output_artifacts,
            key=lambda item: (item.digest, item.size_bytes, item.logical_name or ""),
        )
        if declared_outputs != expected_outputs:
            raise MCRVerificationError(
                "build provenance output artifacts disagree with the output snapshot"
            )
        if (
            provenance.parent_build_id is not None
            and provenance.parent_build_id not in build_provenance
        ):
            raise MCRVerificationError("build provenance parent is not retained in the bundle")
    declared = len(references)
    verified_body_count = verified_structured + verified_opaque
    coverage = EvidenceBodyCoverage(
        declared=declared,
        verified_structured=verified_structured,
        verified_opaque=verified_opaque,
        unavailable=unavailable,
        remote=remote,
        redacted=redacted,
        unrecognized_local=unrecognized_local,
        coverage=verified_body_count / declared if declared else 1.0,
    )
    observation_ids = {
        item.id for item in references.values() if item.kind == "observation"
    }
    observation_bodies_verified = bool(observation_ids) and observation_ids.issubset(
        verified_observation_ids
    )
    metric_set_ids = {
        metric.evidence_set_id for metric in report.metrics if metric.evidence_set_id is not None
    }
    metric_member_ids = {
        member
        for evidence_set in (() if manifest is None else manifest.sets)
        if evidence_set.id in metric_set_ids
        for member in evidence_set.members
    }
    metric_recomputable = (
        release_plan_verified
        and bool(metric_member_ids)
        and metric_member_ids.issubset(verified_observation_ids)
    )
    if require_complete and warnings:
        raise MCRVerificationError(
            f"strict verification requires all linked evidence; found {len(warnings)} warning(s)"
        )
    return MCRVerification(
        bundle_verification_complete=not warnings,
        bundle_component_count=bundle_component_count,
        verified_bundle_component_count=verified_bundle_component_count,
        evidence_body_coverage=coverage,
        metric_recomputable=metric_recomputable,
        observation_bodies_verified=observation_bodies_verified,
        report_id=report.id,
        evidence_id=report.evidence_id,
        run_id=report.run_id,
        decision_status=report.decision.status,
        checks=tuple(dict.fromkeys(checks)),
        warnings=tuple(warnings),
    )
