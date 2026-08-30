"""Offline hero demo: a small overall change hides a severe rare-slice regression."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from merriv.adapters import FakeAdapter
from merriv.core.identity import build_local_snapshot
from merriv.core.models import EvalCase, ModelFamily, RuntimeProfile
from merriv.engine import ObservationCache
from merriv.gate import GatePolicy, GateRule
from merriv.pipeline import ReleaseComparison, compare_exact_match
from merriv.reports import ReportBundle, write_report_bundle


@dataclass(frozen=True, slots=True)
class DemoResult:
    comparison: ReleaseComparison
    bundle: ReportBundle
    warm_cache_hits: int


def run_rare_slice_demo(destination: Path, *, resamples: int = 2_000) -> DemoResult:
    """Run a deterministic base-vs-quantized simulation entirely offline."""
    artifacts = destination / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    baseline_path = artifacts / "model-fp16.bin"
    candidate_path = artifacts / "model-int4.bin"
    baseline_path.write_bytes(b"merriv-demo-fp16")
    candidate_path.write_bytes(b"merriv-demo-int4")
    baseline_snapshot = build_local_snapshot(
        baseline_path,
        model_family=ModelFamily.CV,
        labels={"precision": "fp16", "role": "baseline"},
    )
    candidate_snapshot = build_local_snapshot(
        candidate_path,
        model_family=ModelFamily.CV,
        labels={"precision": "int4", "role": "candidate"},
    )

    cases: list[EvalCase] = []
    baseline_responses: dict[str, str] = {}
    candidate_responses: dict[str, str] = {}
    for index in range(100):
        rare = index >= 90
        case_id = f"case-{index:03d}"
        expected = f"class-{index % 5}"
        cases.append(
            EvalCase(
                case_id=case_id,
                input={"synthetic_feature": index},
                expected=expected,
                slices={"frequency": "rare" if rare else "common"},
            )
        )
        baseline_responses[case_id] = expected
        candidate_responses[case_id] = "wrong-class" if rare and index < 98 else expected

    baseline = FakeAdapter(baseline_snapshot, baseline_responses)
    candidate = FakeAdapter(candidate_snapshot, candidate_responses)
    policy = GatePolicy(
        policy_id="rare-slice-release",
        rules=(
            GateRule(rule_id="overall-quality", metric="accuracy", margin=0.0),
            GateRule(
                rule_id="rare-quality",
                metric="accuracy@frequency=rare",
                margin=0.0,
                min_pairs=10,
            ),
        ),
    )
    cache = ObservationCache(destination / "cache")
    profile = RuntimeProfile(seed=20260828)

    def compare() -> ReleaseComparison:
        return compare_exact_match(
            baseline=baseline,
            candidate=candidate,
            cases=tuple(cases),
            policy=policy,
            cache=cache,
            profile=profile,
            slice_keys=("frequency",),
            baseline_adapter_fingerprint="merriv.fake@1/fp16",
            candidate_adapter_fingerprint="merriv.fake@1/int4",
            resamples=resamples,
        )

    compare()
    comparison = compare()
    bundle = write_report_bundle(
        comparison.report,
        destination / "reports",
        release_plan=comparison.plan,
        evidence_manifest=comparison.evidence_manifest,
    )
    return DemoResult(
        comparison=comparison,
        bundle=bundle,
        warm_cache_hits=comparison.run.cache_hit_count,
    )
