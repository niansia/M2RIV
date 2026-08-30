from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from merriv.adapters import AdapterCapability, FakeAdapter
from merriv.core.identity import build_local_snapshot
from merriv.core.models import EvalCase, ModelSnapshot, Observation, RuntimeProfile
from merriv.engine import CacheKey, ObservationCache, PairedRunner, RunnerContractError


@dataclass
class CountingAdapter:
    delegate: FakeAdapter
    reverse: bool = False
    run_calls: int = 0

    def describe(self) -> ModelSnapshot:
        return self.delegate.describe()

    def capabilities(self) -> frozenset[AdapterCapability]:
        return self.delegate.capabilities()

    def run(
        self,
        cases: Sequence[EvalCase],
        profile: RuntimeProfile,
    ) -> tuple[Observation, ...]:
        self.run_calls += 1
        result = self.delegate.run(cases, profile)
        return tuple(reversed(result)) if self.reverse else result


@dataclass
class MissingCaseAdapter(CountingAdapter):
    def run(
        self,
        cases: Sequence[EvalCase],
        profile: RuntimeProfile,
    ) -> tuple[Observation, ...]:
        result = super().run(cases, profile)
        return result[:-1]


def _adapter(tmp_path: Path, name: str, payload: bytes, label: str) -> CountingAdapter:
    artifact = tmp_path / name
    artifact.write_bytes(payload)
    return CountingAdapter(
        FakeAdapter(
            snapshot=build_local_snapshot(artifact),
            responses={"a": {"label": label, "case": "a"}, "b": {"label": label, "case": "b"}},
        )
    )


def test_paired_runner_pairs_by_case_id_and_hits_cache_on_second_run(tmp_path: Path) -> None:
    baseline = _adapter(tmp_path, "baseline.bin", b"baseline", "baseline")
    candidate = _adapter(tmp_path, "candidate.bin", b"candidate", "candidate")
    baseline.reverse = True
    cases = (EvalCase(case_id="a", input="first"), EvalCase(case_id="b", input="second"))
    profile = RuntimeProfile(seed=7, framework="offline")
    runner = PairedRunner(ObservationCache(tmp_path / "cache"))

    first = runner.run(
        baseline,
        candidate,
        cases,
        profile=profile,
        baseline_adapter_fingerprint="fake@1/baseline",
        candidate_adapter_fingerprint="fake@1/candidate",
    )
    second = runner.run(
        baseline,
        candidate,
        cases,
        profile=profile,
        baseline_adapter_fingerprint="fake@1/baseline",
        candidate_adapter_fingerprint="fake@1/candidate",
    )

    assert [case.case_id for case in first.cases] == ["a", "b"]
    assert first.cases[0].baseline.output == {"label": "baseline", "case": "a"}
    assert first.cache_hit_count == 0
    assert second.cache_hit_count == second.observation_count == 4
    assert baseline.run_calls == candidate.run_calls == 1
    assert not list((tmp_path / "cache").rglob("*.tmp"))


def test_case_content_runtime_and_adapter_fingerprint_invalidate_cache(tmp_path: Path) -> None:
    baseline = _adapter(tmp_path, "baseline.bin", b"baseline", "baseline")
    candidate = _adapter(tmp_path, "candidate.bin", b"candidate", "candidate")
    cache = ObservationCache(tmp_path / "cache")
    runner = PairedRunner(cache)
    original = (EvalCase(case_id="a", input={"revision": 1}),)
    changed = (EvalCase(case_id="a", input={"revision": 2}),)

    runner.run(
        baseline,
        candidate,
        original,
        profile=RuntimeProfile(seed=1),
        baseline_adapter_fingerprint="fake@1",
        candidate_adapter_fingerprint="fake@1",
    )
    content_miss = runner.run(
        baseline,
        candidate,
        changed,
        profile=RuntimeProfile(seed=1),
        baseline_adapter_fingerprint="fake@1",
        candidate_adapter_fingerprint="fake@1",
    )
    profile_miss = runner.run(
        baseline,
        candidate,
        changed,
        profile=RuntimeProfile(seed=2),
        baseline_adapter_fingerprint="fake@1",
        candidate_adapter_fingerprint="fake@1",
    )
    adapter_miss = runner.run(
        baseline,
        candidate,
        changed,
        profile=RuntimeProfile(seed=2),
        baseline_adapter_fingerprint="fake@2",
        candidate_adapter_fingerprint="fake@2",
    )

    assert content_miss.cache_hit_count == 0
    assert profile_miss.cache_hit_count == 0
    assert adapter_miss.cache_hit_count == 0
    assert baseline.run_calls == candidate.run_calls == 4


def test_corrupt_cache_is_a_miss_and_never_a_false_hit(tmp_path: Path) -> None:
    baseline = _adapter(tmp_path, "baseline.bin", b"baseline", "baseline")
    candidate = _adapter(tmp_path, "candidate.bin", b"candidate", "candidate")
    case = EvalCase(case_id="a", input="input")
    profile = RuntimeProfile(seed=3)
    cache = ObservationCache(tmp_path / "cache")
    runner = PairedRunner(cache)
    runner.run(
        baseline,
        candidate,
        (case,),
        profile=profile,
        baseline_adapter_fingerprint="fake@1/baseline",
        candidate_adapter_fingerprint="fake@1/candidate",
    )
    baseline_key = CacheKey.for_case(
        snapshot_id=baseline.describe().id,
        case=case,
        runtime_profile=profile,
        adapter_fingerprint="fake@1/baseline",
    )
    cache.path_for(baseline_key).write_text("{broken", encoding="utf-8")

    result = runner.run(
        baseline,
        candidate,
        (case,),
        profile=profile,
        baseline_adapter_fingerprint="fake@1/baseline",
        candidate_adapter_fingerprint="fake@1/candidate",
    )

    assert result.cases[0].baseline_cache_hit is False
    assert result.cases[0].candidate_cache_hit is True
    assert baseline.run_calls == 2
    assert candidate.run_calls == 1
    assert cache.get(baseline_key) is not None


def test_duplicate_suite_case_ids_are_rejected_before_execution(tmp_path: Path) -> None:
    baseline = _adapter(tmp_path, "baseline.bin", b"baseline", "baseline")
    candidate = _adapter(tmp_path, "candidate.bin", b"candidate", "candidate")
    duplicate_cases = (
        EvalCase(case_id="same", input=1),
        EvalCase(case_id="same", input=2),
    )

    with pytest.raises(RunnerContractError, match="duplicate case_id"):
        PairedRunner(ObservationCache(tmp_path / "cache")).run(
            baseline,
            candidate,
            duplicate_cases,
            profile=RuntimeProfile(),
            baseline_adapter_fingerprint="fake@1",
            candidate_adapter_fingerprint="fake@1",
        )
    assert baseline.run_calls == candidate.run_calls == 0


def test_adapter_missing_a_case_is_rejected_without_caching_partial_batch(tmp_path: Path) -> None:
    good_baseline = _adapter(tmp_path, "baseline.bin", b"baseline", "baseline")
    baseline = MissingCaseAdapter(good_baseline.delegate)
    candidate = _adapter(tmp_path, "candidate.bin", b"candidate", "candidate")
    cases = (EvalCase(case_id="a", input=1), EvalCase(case_id="b", input=2))
    cache = ObservationCache(tmp_path / "cache")

    with pytest.raises(RunnerContractError, match=r"missing=\['b'\]"):
        PairedRunner(cache).run(
            baseline,
            candidate,
            cases,
            profile=RuntimeProfile(),
            baseline_adapter_fingerprint="fake@1/baseline",
            candidate_adapter_fingerprint="fake@1/candidate",
        )

    key = CacheKey.for_case(
        snapshot_id=baseline.describe().id,
        case=cases[0],
        runtime_profile=RuntimeProfile(),
        adapter_fingerprint="fake@1/baseline",
    )
    assert cache.get(key) is None
    assert candidate.run_calls == 0
