"""Backend-free JSON and Markdown MCR renderers."""

from __future__ import annotations

from html import escape

from m2riv.reports.models import ModelChangeReport


def render_json(report: ModelChangeReport) -> str:
    return report.model_dump_json(indent=2) + "\n"


def _format_metric(value: float) -> str:
    return f"{value:+.4f}"


def _markdown_text(value: str, *, table: bool = False) -> str:
    """Keep untrusted report strings as inert, single-line Markdown text."""
    single_line = "".join(
        " "
        if character in "\r\n" or ord(character) < 32 or 127 <= ord(character) < 160
        else character
        for character in value
    )
    safe = escape(single_line, quote=False).replace("`", "&#96;")
    safe = safe.replace("*", "\\*").replace("[", "\\[").replace("]", "\\]")
    if table:
        safe = safe.replace("|", "\\|")
    return safe


def render_markdown(report: ModelChangeReport) -> str:
    lines = [
        "# Model Change Report",
        "",
        f"**Evaluation decision: {report.decision.status.value}**",
        "",
        "- Evaluation policy satisfied: "
        f"`{str(report.decision.evaluation_policy_satisfied).lower()}`",
        "- Deployment authorization: `not-evaluated` (consumer-side)",
        "",
        f"- Baseline: `{report.baseline_snapshot_id}`",
        f"- Candidate: `{report.candidate_snapshot_id}`",
        f"- Report: `{report.id}`",
        f"- Evidence: `{report.evidence_id}`",
        f"- Run: `{report.run_id}`",
        "",
        "## Metric changes",
        "",
        "| Metric | Scope | Direction | Unit | Baseline | Candidate | Delta | CI | n |",
        "|---|---|---|---|---:|---:|---:|---:|---:|",
    ]
    if report.release_plan_id is not None:
        lines.insert(12, f"- Release plan: `{report.release_plan_id}`")
    for metric in report.metrics:
        interval = "-"
        if metric.interval_lower is not None and metric.interval_upper is not None:
            interval = (
                f"[{_format_metric(metric.interval_lower)}, "
                f"{_format_metric(metric.interval_upper)}] "
                f"({metric.confidence_level:.1%})"
            )
        lines.append(
            f"| {_markdown_text(metric.metric_id, table=True)} | "
            f"{_markdown_text(metric.scope, table=True)} | {metric.direction} | "
            f"{_markdown_text(metric.unit, table=True)} | "
            f"{metric.baseline_value:.4f} | "
            f"{metric.candidate_value:.4f} | {_format_metric(metric.delta)} | "
            f"{interval} | {metric.sample_size} |"
        )

    metric_sets = tuple(metric for metric in report.metrics if metric.evidence_set_id is not None)
    if metric_sets:
        lines.extend(
            [
                "",
                "## Metric evidence sets",
                "",
                "| Metric | Scope | Evidence set |",
                "|---|---|---|",
            ]
        )
        lines.extend(
            f"| {_markdown_text(metric.metric_id, table=True)} | "
            f"{_markdown_text(metric.scope, table=True)} | `{metric.evidence_set_id}` |"
            for metric in metric_sets
        )

    if report.executions:
        lines.extend(
            [
                "",
                "## Execution provenance",
                "",
                "| Role | Executor | Version | Dispatched | Returned | Cache hits |",
                "|---|---|---|---:|---:|---:|",
            ]
        )
        lines.extend(
            f"| {execution.role} | "
            f"{_markdown_text(execution.executor_id, table=True)} | "
            f"{_markdown_text(execution.executor_version, table=True)} | "
            f"{execution.requested_cases} | {execution.returned_observations} | "
            f"{execution.cache_hits} |"
            for execution in report.executions
        )

    portable_evidence = tuple(
        evidence for evidence in report.evidence if evidence.kind != "observation"
    )
    if report.evidence_manifest is not None or portable_evidence:
        lines.extend(
            [
                "",
                "## Linked evidence",
                "",
                "| Kind | Content ID | URI |",
                "|---|---|---|",
            ]
        )
        if report.evidence_manifest is not None:
            manifest = report.evidence_manifest
            lines.append(
                f"| evidence-manifest | `{manifest.id}` | "
                f"{_markdown_text(manifest.uri, table=True)} |"
            )
        lines.extend(
            f"| {_markdown_text(evidence.kind, table=True)} | `{evidence.id}` | "
            f"{_markdown_text(evidence.uri or '-', table=True)} |"
            for evidence in portable_evidence
        )

    if report.decision.findings:
        lines.extend(
            [
                "",
                "## Gate findings",
                "",
                f"Multiplicity: `{report.decision.multiple_comparison_method}` · "
                f"family alpha: `{report.decision.familywise_alpha}` · "
                f"family size: `{report.decision.family_size}` · "
                f"target power: `{report.decision.target_power}`",
                "",
            ]
        )
        lines.extend(
            f"- **{finding.status.value}** "
            f"{_markdown_text(finding.rule_id)}: {_markdown_text(finding.message)}"
            + (
                f" (evidence set `{finding.evidence_set_id}`)"
                if finding.evidence_set_id is not None
                else ""
            )
            for finding in report.decision.findings
        )
    if report.limitations:
        lines.extend(["", "## Limitations", ""])
        lines.extend(f"- {_markdown_text(limitation)}" for limitation in report.limitations)
    return "\n".join(lines) + "\n"
