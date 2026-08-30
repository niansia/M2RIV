"""Portable Model Change Report contracts and renderers."""

from merriv.reports.ci import render_junit, render_sarif
from merriv.reports.io import ReportBundle, write_report_bundle
from merriv.reports.models import (
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
from merriv.reports.render import render_json, render_markdown
from merriv.reports.verify import (
    MCRTrustState,
    MCRVerification,
    MCRVerificationError,
    verify_report_bundle,
)

__all__ = [
    "EvidenceManifest",
    "EvidenceManifestRef",
    "EvidenceSet",
    "MCRDecision",
    "MCRExecution",
    "MCRFinding",
    "MCRMetric",
    "MCRStatus",
    "MCRTrustState",
    "MCRVerification",
    "MCRVerificationError",
    "ModelChangeReport",
    "ReportBundle",
    "create_evidence_manifest",
    "create_evidence_set",
    "create_report",
    "render_json",
    "render_junit",
    "render_markdown",
    "render_sarif",
    "verify_report_bundle",
    "write_report_bundle",
]
