"""Generate normative MCR 0.4 positive and must-reject conformance vectors."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from merriv.conformance import normative_profile_report
from merriv.core.identity import fingerprint
from merriv.core.models import EvidenceRef
from merriv.reports import MCRStatus, create_report, render_json

ROOT = Path(__file__).parent


def _missing_evidence_report() -> str:
    base = normative_profile_report(MCRStatus.PASS)
    missing = EvidenceRef(
        id=f"mcr:sha256:{fingerprint('missing-artifact-diff', namespace='negative-fixture')}",
        kind="artifact-diff",
        uri="missing-artifact-diff.json",
    )
    report = create_report(
        baseline_snapshot_id=base.baseline_snapshot_id,
        candidate_snapshot_id=base.candidate_snapshot_id,
        executions=base.executions,
        metrics=base.metrics,
        decision=base.decision,
        evidence=(missing,),
        limitations=base.limitations,
        created_at=base.created_at,
    )
    return render_json(report)


def _mutated_report(mutator: str) -> str:
    payload: dict[str, Any] = json.loads(render_json(normative_profile_report(MCRStatus.PASS)))
    if mutator == "tampered-id":
        payload["id"] = "mcr:sha256:" + "0" * 64
    elif mutator == "unknown-version":
        payload["schema_version"] = "0.5.0"
    elif mutator == "decision-mismatch":
        payload["decision"]["status"] = "BLOCK"
        payload["decision"]["allowed"] = True
        payload["decision"]["findings"][0]["status"] = "BLOCK"
    else:
        raise ValueError(f"unknown negative fixture: {mutator}")
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _expected_files() -> dict[Path, str]:
    files = {
        ROOT / status.value.lower() / "mcr-report.json": render_json(
            normative_profile_report(status)
        )
        for status in (
            MCRStatus.PASS,
            MCRStatus.WARN,
            MCRStatus.INSUFFICIENT_POWER,
            MCRStatus.BLOCK,
            MCRStatus.ERROR,
        )
    }
    files[ROOT / "negative" / "missing-evidence" / "mcr-report.json"] = (
        _missing_evidence_report()
    )
    for name in ("tampered-id", "unknown-version", "decision-mismatch"):
        files[ROOT / "negative" / name / "mcr-report.json"] = _mutated_report(name)
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    changed: list[str] = []
    for destination, expected in _expected_files().items():
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
