"""Generate minimal producer-neutral MCR 1.3 conformance fixtures."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from m2riv.core.identity import fingerprint
from m2riv.core.models import RuntimeProfile
from m2riv.reports import (
    MCRDecision,
    MCRExecution,
    MCRFinding,
    MCRMetric,
    MCRStatus,
    create_report,
    render_json,
)

ROOT = Path(__file__).parent


def _content_id(label: str) -> str:
    return f"m2riv:sha256:{fingerprint(label, namespace='external-fixture')}"


def fixture_source(status: MCRStatus) -> str:
    allowed = status is MCRStatus.PASS
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
        returned_observations=10,
    )
    delta = {MCRStatus.PASS: 0.0, MCRStatus.WARN: -0.02, MCRStatus.BLOCK: -0.2}[status]
    metric = MCRMetric(
        metric_id="accuracy",
        baseline_value=0.9,
        candidate_value=0.9 + delta,
        delta=delta,
        sample_size=10,
    )
    finding = MCRFinding(
        rule_id="accuracy-floor",
        status=status,
        metric_id="accuracy",
        message=f"external producer fixture: {status.value}",
    )
    report = create_report(
        baseline_snapshot_id=_content_id("baseline"),
        candidate_snapshot_id=_content_id(f"candidate-{status.value.lower()}"),
        executions=(execution,),
        metrics=(metric,),
        decision=MCRDecision(status=status, allowed=allowed, findings=(finding,)),
        limitations=("Minimal external-producer conformance fixture; no model was run.",),
        created_at=datetime(2026, 8, 29, tzinfo=UTC),
    )
    return render_json(report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    changed: list[str] = []
    for status in (MCRStatus.PASS, MCRStatus.WARN, MCRStatus.BLOCK):
        destination = ROOT / status.value.lower() / "m2riv-report.json"
        expected = fixture_source(status)
        if destination.exists() and destination.read_text("utf-8") == expected:
            continue
        changed.append(destination.relative_to(ROOT).as_posix())
        if not arguments.check:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(expected, encoding="utf-8", newline="\n")
    if arguments.check and changed:
        parser.error(f"stale conformance fixtures: {', '.join(changed)}")


if __name__ == "__main__":
    main()
