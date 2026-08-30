"""CI-native JUnit and SARIF renderers for Model Change Reports."""

from __future__ import annotations

import json

# This module only constructs XML; it never parses untrusted XML input.
from xml.etree import ElementTree  # nosec B405

from m2riv.reports.models import MCRStatus, ModelChangeReport


def _xml_text(value: str) -> str:
    """Replace characters XML 1.0 cannot represent before building CI output."""
    return "".join(
        character
        if character in "\t\n\r"
        or 0x20 <= ord(character) <= 0xD7FF
        or 0xE000 <= ord(character) <= 0xFFFD
        or 0x10000 <= ord(character) <= 0x10FFFF
        else " "
        for character in value
    )


def render_junit(report: ModelChangeReport) -> str:
    """Render gate findings into a broadly compatible JUnit testsuite."""
    findings = report.decision.findings
    test_count = max(1, len(findings))
    failures = sum(
        finding.status is MCRStatus.BLOCK
        or finding.status is MCRStatus.INSUFFICIENT_POWER
        or (
            finding.status is MCRStatus.WARN
            and not report.decision.evaluation_policy_satisfied
        )
        for finding in findings
    )
    errors = sum(finding.status is MCRStatus.ERROR for finding in findings)
    suite = ElementTree.Element(
        "testsuite",
        {
            "name": "m2riv.release-gate",
            "tests": str(test_count),
            "failures": str(failures),
            "errors": str(errors),
            "skipped": "0",
            "time": "0",
        },
    )
    if not findings:
        ElementTree.SubElement(
            suite,
            "testcase",
            {"classname": "m2riv.gate", "name": "release-decision", "time": "0"},
        )
    for finding in findings:
        case = ElementTree.SubElement(
            suite,
            "testcase",
            {"classname": "m2riv.gate", "name": _xml_text(finding.rule_id), "time": "0"},
        )
        if finding.status in {MCRStatus.BLOCK, MCRStatus.INSUFFICIENT_POWER} or (
            finding.status is MCRStatus.WARN
            and not report.decision.evaluation_policy_satisfied
        ):
            safe_message = _xml_text(finding.message)
            child = ElementTree.SubElement(case, "failure", {"message": safe_message})
            child.text = safe_message
        elif finding.status is MCRStatus.ERROR:
            safe_message = _xml_text(finding.message)
            child = ElementTree.SubElement(case, "error", {"message": safe_message})
            child.text = safe_message
        elif finding.status is MCRStatus.WARN:
            child = ElementTree.SubElement(case, "system-out")
            child.text = f"WARN: {_xml_text(finding.message)}"
    ElementTree.indent(suite, space="  ")
    return ElementTree.tostring(suite, encoding="unicode", xml_declaration=True) + "\n"


def render_sarif(report: ModelChangeReport) -> str:
    """Render non-PASS gate findings as SARIF 2.1.0 results."""
    non_pass = tuple(
        finding for finding in report.decision.findings if finding.status is not MCRStatus.PASS
    )
    rules = [
        {
            "id": finding.rule_id,
            "name": finding.metric_id or finding.rule_id,
            "shortDescription": {"text": finding.message},
            "properties": {"m2rivStatus": finding.status.value},
        }
        for finding in non_pass
    ]
    results = [
        {
            "ruleId": finding.rule_id,
            "level": (
                "error"
                if finding.status
                in {MCRStatus.BLOCK, MCRStatus.INSUFFICIENT_POWER, MCRStatus.ERROR}
                or (
                    finding.status is MCRStatus.WARN
                    and not report.decision.evaluation_policy_satisfied
                )
                else "warning"
            ),
            "message": {"text": finding.message},
            "properties": {
                "m2rivStatus": finding.status.value,
                "evaluationPolicySatisfied": report.decision.evaluation_policy_satisfied,
                "deploymentAuthorization": "not-evaluated",
                "metricId": finding.metric_id,
                "reportId": report.id,
            },
        }
        for finding in non_pass
    ]
    document = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Merriv",
                        "informationUri": "https://github.com/niansia/Merriv",
                        "rules": rules,
                    }
                },
                "results": results,
                "properties": {
                    "evaluationDecision": report.decision.status.value,
                    "deploymentAuthorization": "not-evaluated",
                    "reportId": report.id,
                },
            }
        ],
    }
    return json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
