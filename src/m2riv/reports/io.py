"""Crash-safe local report bundle persistence."""

from __future__ import annotations

import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from m2riv.core.identity import has_link_like_component
from m2riv.planning import CompiledReleasePlan
from m2riv.reports.ci import render_junit, render_sarif
from m2riv.reports.models import (
    EvidenceManifest,
    ModelChangeReport,
    create_evidence_manifest,
    create_report,
)
from m2riv.reports.render import render_json, render_markdown


@dataclass(frozen=True, slots=True)
class ReportBundle:
    json_path: Path
    markdown_path: Path
    junit_path: Path
    sarif_path: Path
    plan_path: Path | None = None
    evidence_manifest_path: Path | None = None


def _is_reparse_or_symlink(path_stat: os.stat_result) -> bool:
    attributes = getattr(path_stat, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(path_stat.st_mode) or bool(attributes & reparse_flag)


def _safe_directory(path: Path) -> bool:
    try:
        path_stat = path.lstat()
    except OSError:
        return False
    return (
        stat.S_ISDIR(path_stat.st_mode)
        and not _is_reparse_or_symlink(path_stat)
        and not has_link_like_component(path)
    )


def _prepare_destination(destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        if not _safe_directory(destination):
            raise ValueError("report destination must be a regular local directory")
        return
    missing: list[Path] = []
    cursor = destination
    while not cursor.exists() and not cursor.is_symlink():
        missing.append(cursor)
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    if not _safe_directory(cursor):
        raise ValueError("report destination parent must be a regular local directory")
    for directory in reversed(missing):
        directory.mkdir()
        if not _safe_directory(directory):
            raise ValueError("report destination changed during creation")


def _atomic_write_text(target: Path, content: str) -> None:
    if not _safe_directory(target.parent):
        raise ValueError("report destination must be a regular local directory")
    if target.exists() or target.is_symlink():
        target_stat = target.lstat()
        if not stat.S_ISREG(target_stat.st_mode) or _is_reparse_or_symlink(target_stat):
            raise ValueError("report target must be a regular file")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if not _safe_directory(target.parent):
            raise ValueError("report destination changed during write")
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def write_report_bundle(
    report: ModelChangeReport,
    destination: Path,
    *,
    release_plan: CompiledReleasePlan | None = None,
    evidence_manifest: EvidenceManifest | None = None,
) -> ReportBundle:
    """Atomically publish canonical JSON and human-readable Markdown."""
    canonical_report = create_report(
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
        canonical_report.id != report.id
        or canonical_report.evidence_id != report.evidence_id
        or canonical_report.run_id != report.run_id
    ):
        raise ValueError("MCR identity does not match its contents")
    if release_plan is not None and report.release_plan_id != release_plan.id:
        raise ValueError("release plan identity does not match the MCR reference")
    if (report.evidence_manifest is None) is not (evidence_manifest is None):
        raise ValueError("MCR and evidence manifest must be provided together")
    if evidence_manifest is not None:
        canonical_manifest = create_evidence_manifest(
            evidence_manifest.evidence, evidence_manifest.sets
        )
        reference = report.evidence_manifest
        if canonical_manifest.id != evidence_manifest.id:
            raise ValueError("evidence manifest identity does not match its contents")
        if (
            reference is None
            or reference.id != evidence_manifest.id
            or reference.evidence_count != len(evidence_manifest.evidence)
            or reference.set_count != len(evidence_manifest.sets)
        ):
            raise ValueError("evidence manifest identity does not match the MCR reference")
        available_sets = {item.id for item in evidence_manifest.sets}
        if any(
            metric.evidence_set_id is not None and metric.evidence_set_id not in available_sets
            for metric in report.metrics
        ):
            raise ValueError("MCR metric references an unknown evidence set")
        if any(
            finding.evidence_set_id is not None and finding.evidence_set_id not in available_sets
            for finding in report.decision.findings
        ):
            raise ValueError("MCR finding references an unknown evidence set")
    _prepare_destination(destination)
    plan_path: Path | None = None
    if release_plan is not None:
        plan_path = destination / "release-plan.json"
        _atomic_write_text(plan_path, release_plan.model_dump_json(indent=2) + "\n")
    evidence_manifest_path: Path | None = None
    if evidence_manifest is not None:
        evidence_manifest_path = destination / "evidence-manifest.json"
        _atomic_write_text(
            evidence_manifest_path, evidence_manifest.model_dump_json(indent=2) + "\n"
        )
    json_path = destination / "mcr-report.json"
    markdown_path = destination / "summary.md"
    junit_path = destination / "junit.xml"
    sarif_path = destination / "results.sarif"
    _atomic_write_text(json_path, render_json(report))
    _atomic_write_text(markdown_path, render_markdown(report))
    _atomic_write_text(junit_path, render_junit(report))
    _atomic_write_text(sarif_path, render_sarif(report))
    return ReportBundle(
        plan_path=plan_path,
        evidence_manifest_path=evidence_manifest_path,
        json_path=json_path,
        markdown_path=markdown_path,
        junit_path=junit_path,
        sarif_path=sarif_path,
    )
