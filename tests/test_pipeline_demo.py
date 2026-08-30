from __future__ import annotations

from pathlib import Path

from merriv.demo import run_rare_slice_demo
from merriv.gate import GateStatus
from merriv.reports import ModelChangeReport


def test_rare_slice_demo_blocks_and_reuses_cache(tmp_path: Path) -> None:
    result = run_rare_slice_demo(tmp_path, resamples=500)

    assert result.comparison.gate.status is GateStatus.BLOCK
    assert all(
        finding.evidence_set_id is not None
        for finding in result.comparison.report.decision.findings
    )
    assert result.warm_cache_hits == result.comparison.run.observation_count == 200
    metrics = {metric.metric_id: metric for metric in result.comparison.report.metrics}
    assert metrics["accuracy"].delta == -0.08
    assert metrics["accuracy@frequency=rare"].delta == -0.8
    assert result.bundle.json_path.exists()
    assert result.bundle.markdown_path.exists()
    assert result.bundle.plan_path is not None
    assert result.bundle.plan_path.exists()
    assert result.bundle.evidence_manifest_path is not None
    assert result.bundle.evidence_manifest_path.exists()
    assert (
        ModelChangeReport.model_validate_json(result.bundle.json_path.read_text("utf-8")).id
        == result.comparison.report.id
    )
