"""Portable Model Change Report contracts and renderers."""

from m2riv.reports.ci import render_junit, render_sarif
from m2riv.reports.io import ReportBundle, write_report_bundle
from m2riv.reports.models import (
    EvidenceManifest,
    EvidenceManifestRef,
    EvidenceSet,
    MCRDecision,
    MCRExecution,
    MCRFinding,
    MCRMetric,
    MCRStatus,
    ModelChangeReport,
    create_evidence_manifest,
    create_evidence_set,
    create_report,
)
from m2riv.reports.render import render_json, render_markdown

__all__ = [
    "EvidenceManifest",
    "EvidenceManifestRef",
    "EvidenceSet",
    "MCRDecision",
    "MCRExecution",
    "MCRFinding",
    "MCRMetric",
    "MCRStatus",
    "ModelChangeReport",
    "ReportBundle",
    "create_evidence_manifest",
    "create_evidence_set",
    "create_report",
    "render_json",
    "render_junit",
    "render_markdown",
    "render_sarif",
    "write_report_bundle",
]
