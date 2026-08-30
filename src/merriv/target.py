"""Cryptographic root manifest for retained target execution evidence."""

from __future__ import annotations

import os
import stat
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from merriv.core.identity import fingerprint, hash_artifact, read_verified_file
from merriv.core.models import ContentId, Contract, RuntimeProfile, SafeCaseId
from merriv.evidence import FileDigestBinding
from merriv.io.json import StrictJSONError, parse_strict_json
from merriv.reports.io import _atomic_write_text
from merriv.reports.verify import MCRVerificationError, verify_report_bundle

TARGET_MANIFEST_NAME = "target-evidence-manifest.json"
MAX_TARGET_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_TARGET_FILES = 100_000
MAX_TARGET_ENTRIES = 200_000
MAX_TARGET_BYTES = 64 * 1024 * 1024 * 1024


def _is_link_like(path_stat: os.stat_result) -> bool:
    attributes = getattr(path_stat, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(path_stat.st_mode) or bool(attributes & reparse_flag)


def _retained_files(root: Path, manifest_path: Path) -> tuple[Path, ...]:
    retained: list[Path] = []
    entries = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        entries += 1
        if entries > MAX_TARGET_ENTRIES:
            raise MCRVerificationError("target evidence tree exceeds the traversal limit")
        try:
            path_stat = path.lstat()
        except OSError as error:
            raise MCRVerificationError("target evidence entry changed during traversal") from error
        if _is_link_like(path_stat):
            raise MCRVerificationError(
                "target evidence tree must not contain links or reparse points"
            )
        if stat.S_ISDIR(path_stat.st_mode):
            continue
        if not stat.S_ISREG(path_stat.st_mode):
            raise MCRVerificationError("target evidence tree must contain only regular files")
        if path == manifest_path:
            continue
        retained.append(path)
        if len(retained) > MAX_TARGET_FILES:
            raise MCRVerificationError("target evidence tree exceeds the file limit")
    return tuple(retained)


def _safe_relative(value: str) -> str:
    relative = PurePosixPath(value.replace("\\", "/"))
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
        raise ValueError("target evidence path must be safe and relative")
    return relative.as_posix()


class TargetReportBinding(Contract):
    """One strictly verified MCR bundle retained below the target root."""

    build_name: SafeCaseId
    directory: Annotated[str, StringConstraints(min_length=1, max_length=2048)]
    report_id: ContentId
    evidence_id: ContentId
    run_id: ContentId

    @field_validator("directory")
    @classmethod
    def directory_is_safe(cls, value: str) -> str:
        return _safe_relative(value)


class TargetEvidenceManifest(Contract):
    """One root identity covering every retained target evidence byte."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    id: ContentId
    source_commit: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{40,64}$")]
    target_profile: RuntimeProfile
    tool_versions: dict[str, str] = Field(min_length=1, max_length=128)
    files: tuple[FileDigestBinding, ...] = Field(min_length=1, max_length=MAX_TARGET_FILES)
    reports: tuple[TargetReportBinding, ...] = Field(min_length=1, max_length=10_000)
    first_bad_build: SafeCaseId | None = None

    @model_validator(mode="after")
    def paths_and_builds_are_unique(self) -> TargetEvidenceManifest:
        uris = [item.uri for item in self.files]
        if len(uris) != len(set(uris)):
            raise ValueError("target evidence file URIs must be unique")
        builds = [item.build_name for item in self.reports]
        if len(builds) != len(set(builds)):
            raise ValueError("target evidence report build names must be unique")
        if sum(item.size_bytes for item in self.files) > MAX_TARGET_BYTES:
            raise ValueError("target evidence files exceed the total byte limit")
        return self


class TargetEvidenceVerification(Contract):
    schema_version: Literal["0.1.0"] = "0.1.0"
    valid: Literal[True] = True
    target_evidence_id: ContentId
    verified_file_count: int = Field(ge=1)
    verified_report_count: int = Field(ge=1)
    source_commit: str
    first_bad_build: str | None = None


def _manifest_payload(
    *,
    source_commit: str,
    target_profile: RuntimeProfile,
    tool_versions: dict[str, str],
    files: tuple[FileDigestBinding, ...],
    reports: tuple[TargetReportBinding, ...],
    first_bad_build: str | None,
) -> dict[str, object]:
    return {
        "source_commit": source_commit,
        "target_profile": target_profile,
        "tool_versions": tool_versions,
        "files": files,
        "reports": reports,
        "first_bad_build": first_bad_build,
    }


def create_target_evidence_manifest(
    *,
    root: Path,
    source_commit: str,
    target_profile: RuntimeProfile,
    tool_versions: dict[str, str],
    report_builds: tuple[tuple[str, str], ...],
    first_bad_build: str | None,
) -> TargetEvidenceManifest:
    """Hash a complete retained target tree and strictly bind its MCR bundles."""
    files: list[FileDigestBinding] = []
    total_bytes = 0
    manifest_path = root / TARGET_MANIFEST_NAME
    for path in _retained_files(root, manifest_path):
        relative = path.relative_to(root)
        digest = hash_artifact(path)
        total_bytes += digest.size_bytes
        if total_bytes > MAX_TARGET_BYTES:
            raise MCRVerificationError("target evidence files exceed the total byte limit")
        files.append(
            FileDigestBinding(
                uri=relative.as_posix(),
                sha256=digest.digest,
                size_bytes=digest.size_bytes,
                logical_name=path.name,
            )
        )
    reports: list[TargetReportBinding] = []
    for build_name, directory in report_builds:
        verification = verify_report_bundle(root / _safe_relative(directory), require_complete=True)
        reports.append(
            TargetReportBinding(
                build_name=build_name,
                directory=directory,
                report_id=verification.report_id,
                evidence_id=verification.evidence_id,
                run_id=verification.run_id,
            )
        )
    payload = _manifest_payload(
        source_commit=source_commit,
        target_profile=target_profile,
        tool_versions=tool_versions,
        files=tuple(files),
        reports=tuple(reports),
        first_bad_build=first_bad_build,
    )
    identifier = fingerprint(payload, namespace="target-evidence-manifest")
    return TargetEvidenceManifest(
        id=f"mcr:sha256:{identifier}",
        source_commit=source_commit,
        target_profile=target_profile,
        tool_versions=tool_versions,
        files=tuple(files),
        reports=tuple(reports),
        first_bad_build=first_bad_build,
    )


def write_target_evidence_manifest(manifest: TargetEvidenceManifest, path: Path) -> None:
    _atomic_write_text(path, manifest.model_dump_json(indent=2) + "\n")


def verify_target_evidence_manifest(source: str | Path) -> TargetEvidenceVerification:
    """Verify the root identity, every retained file, and every MCR bundle."""
    requested = Path(source)
    manifest_path = requested / TARGET_MANIFEST_NAME if requested.is_dir() else requested
    root = manifest_path.parent
    try:
        payload = parse_strict_json(
            read_verified_file(manifest_path, max_bytes=MAX_TARGET_MANIFEST_BYTES)
        )
        manifest = TargetEvidenceManifest.model_validate(payload)
    except (OSError, ValueError, StrictJSONError) as error:
        raise MCRVerificationError("target evidence manifest is unavailable or invalid") from error
    canonical_payload = _manifest_payload(
        source_commit=manifest.source_commit,
        target_profile=manifest.target_profile,
        tool_versions=manifest.tool_versions,
        files=manifest.files,
        reports=manifest.reports,
        first_bad_build=manifest.first_bad_build,
    )
    expected_digest = fingerprint(canonical_payload, namespace="target-evidence-manifest")
    expected_id = f"mcr:sha256:{expected_digest}"
    if manifest.id != expected_id:
        raise MCRVerificationError("target evidence root identity does not match its contents")
    declared = {item.uri: item for item in manifest.files}
    retained = _retained_files(root, manifest_path)
    actual_paths = {path.relative_to(root).as_posix() for path in retained}
    if actual_paths != set(declared):
        raise MCRVerificationError("target evidence tree has missing or unlisted retained files")
    for uri, binding in declared.items():
        path = root / PurePosixPath(_safe_relative(uri))
        digest = hash_artifact(path)
        if digest.file_count != 1 or digest.digest != binding.sha256:
            raise MCRVerificationError(f"target evidence file digest changed: {uri}")
        if digest.size_bytes != binding.size_bytes:
            raise MCRVerificationError(f"target evidence file size changed: {uri}")
    for report in manifest.reports:
        verification = verify_report_bundle(root / report.directory, require_complete=True)
        if (
            verification.report_id != report.report_id
            or verification.evidence_id != report.evidence_id
            or verification.run_id != report.run_id
        ):
            raise MCRVerificationError(
                f"target report binding changed for build {report.build_name}"
            )
    return TargetEvidenceVerification(
        target_evidence_id=manifest.id,
        verified_file_count=len(manifest.files),
        verified_report_count=len(manifest.reports),
        source_commit=manifest.source_commit,
        first_bad_build=manifest.first_bad_build,
    )
