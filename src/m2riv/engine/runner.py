"""Deterministic paired execution across baseline and candidate snapshots."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from m2riv.adapters import OpenAICompatibleError
from m2riv.adapters.base import ModelAdapter
from m2riv.core.identity import fingerprint
from m2riv.core.models import EvalCase, ModelSnapshot, Observation, RetentionMode, RuntimeProfile
from m2riv.engine.cache import CacheKey, ObservationCache
from m2riv.execution import ExecutionBackend, ExecutorDescriptor, LocalExecutor


class RunnerContractError(ValueError):
    """An adapter or evaluation suite violated the paired-run contract."""


@dataclass(frozen=True, slots=True)
class PairedCaseResult:
    """Baseline and candidate evidence for exactly one evaluation case."""

    case: EvalCase
    baseline: Observation
    candidate: Observation
    baseline_cache_hit: bool
    candidate_cache_hit: bool

    @property
    def case_id(self) -> str:
        return self.case.case_id


@dataclass(frozen=True, slots=True)
class PairedRunResult:
    """Ordered paired evidence plus cache provenance for downstream analysis."""

    baseline_snapshot: ModelSnapshot
    candidate_snapshot: ModelSnapshot
    runtime_profile: RuntimeProfile
    cases: tuple[PairedCaseResult, ...]
    baseline_execution: ExecutionTrace
    candidate_execution: ExecutionTrace

    @property
    def cache_hit_count(self) -> int:
        return sum(
            int(case.baseline_cache_hit) + int(case.candidate_cache_hit) for case in self.cases
        )

    @property
    def observation_count(self) -> int:
        return len(self.cases) * 2


@dataclass(frozen=True, slots=True)
class _SideResult:
    observations: dict[str, Observation]
    cache_hits: frozenset[str]
    execution: ExecutionTrace


@dataclass(frozen=True, slots=True)
class ExecutionTrace:
    """Executor provenance and the amount of work actually dispatched."""

    descriptor: ExecutorDescriptor
    requested_cases: int
    returned_observations: int


class PairedRunner:
    """Run two model snapshots against one suite and pair evidence by case ID."""

    def __init__(
        self,
        cache: ObservationCache,
        *,
        baseline_executor: ExecutionBackend | None = None,
        candidate_executor: ExecutionBackend | None = None,
    ) -> None:
        self.cache = cache
        self.baseline_executor = baseline_executor or LocalExecutor()
        self.candidate_executor = candidate_executor or LocalExecutor()

    def run(
        self,
        baseline: ModelAdapter,
        candidate: ModelAdapter,
        cases: Sequence[EvalCase],
        *,
        profile: RuntimeProfile,
        baseline_adapter_fingerprint: str,
        candidate_adapter_fingerprint: str,
    ) -> PairedRunResult:
        """Execute cache misses and return results in evaluation-suite order."""
        ordered_cases = tuple(cases)
        self._validate_case_ids(ordered_cases)
        baseline_snapshot = baseline.describe()
        candidate_snapshot = candidate.describe()

        baseline_result = self._run_side(
            adapter=baseline,
            snapshot=baseline_snapshot,
            cases=ordered_cases,
            profile=profile,
            adapter_fingerprint=baseline_adapter_fingerprint,
            executor=self.baseline_executor,
        )
        candidate_result = self._run_side(
            adapter=candidate,
            snapshot=candidate_snapshot,
            cases=ordered_cases,
            profile=profile,
            adapter_fingerprint=candidate_adapter_fingerprint,
            executor=self.candidate_executor,
        )

        paired = tuple(
            PairedCaseResult(
                case=case,
                baseline=baseline_result.observations[case.case_id],
                candidate=candidate_result.observations[case.case_id],
                baseline_cache_hit=case.case_id in baseline_result.cache_hits,
                candidate_cache_hit=case.case_id in candidate_result.cache_hits,
            )
            for case in ordered_cases
        )
        return PairedRunResult(
            baseline_snapshot=baseline_snapshot,
            candidate_snapshot=candidate_snapshot,
            runtime_profile=profile,
            cases=paired,
            baseline_execution=baseline_result.execution,
            candidate_execution=candidate_result.execution,
        )

    @staticmethod
    def _validate_case_ids(cases: tuple[EvalCase, ...]) -> None:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for case in cases:
            if case.case_id in seen:
                duplicates.add(case.case_id)
            seen.add(case.case_id)
        if duplicates:
            rendered = ", ".join(sorted(duplicates))
            raise RunnerContractError(
                f"evaluation suite contains duplicate case_id values: {rendered}"
            )

    def _run_side(
        self,
        *,
        adapter: ModelAdapter,
        snapshot: ModelSnapshot,
        cases: tuple[EvalCase, ...],
        profile: RuntimeProfile,
        adapter_fingerprint: str,
        executor: ExecutionBackend,
    ) -> _SideResult:
        try:
            descriptor = ExecutorDescriptor.model_validate(executor.describe())
        except Exception:
            raise RunnerContractError("execution backend description failed") from None
        executor_fingerprint = fingerprint(descriptor, namespace="executor-cache-identity")
        keys = {
            case.case_id: CacheKey.for_case(
                snapshot_id=snapshot.id,
                case=case,
                runtime_profile=profile,
                adapter_fingerprint=adapter_fingerprint,
                executor_fingerprint=executor_fingerprint,
            )
            for case in cases
        }
        observations: dict[str, Observation] = {}
        cache_hits: set[str] = set()
        misses: list[EvalCase] = []
        for case in cases:
            cached = self.cache.get(keys[case.case_id])
            if cached is None:
                misses.append(case)
            else:
                observations[case.case_id] = cached
                cache_hits.add(case.case_id)

        if misses:
            try:
                fresh = executor.execute(adapter, misses, profile)
            except OpenAICompatibleError as error:
                if type(executor) is LocalExecutor and type(error) is OpenAICompatibleError:
                    raise
                raise RunnerContractError(
                    f"execution backend {descriptor.executor_id!r} failed"
                ) from None
            except Exception:
                raise RunnerContractError(
                    f"execution backend {descriptor.executor_id!r} failed"
                ) from None
            fresh_by_id = self._validate_observations(
                observations=fresh,
                requested=tuple(misses),
                snapshot=snapshot,
            )
            for case in misses:
                observation = fresh_by_id[case.case_id]
                self.cache.put(keys[case.case_id], observation)
                observations[case.case_id] = observation

        return _SideResult(
            observations=observations,
            cache_hits=frozenset(cache_hits),
            execution=ExecutionTrace(
                descriptor=descriptor,
                requested_cases=len(misses),
                returned_observations=len(fresh) if misses else 0,
            ),
        )

    @staticmethod
    def _validate_observations(
        *,
        observations: Sequence[Observation],
        requested: tuple[EvalCase, ...],
        snapshot: ModelSnapshot,
    ) -> dict[str, Observation]:
        requested_ids = {case.case_id for case in requested}
        by_id: dict[str, Observation] = {}
        duplicates: set[str] = set()
        for observation in observations:
            if observation.case_id in by_id:
                duplicates.add(observation.case_id)
            by_id[observation.case_id] = observation
            if observation.snapshot_id != snapshot.id:
                raise RunnerContractError(
                    f"adapter returned case {observation.case_id!r} for the wrong snapshot"
                )
            if observation.retention == RetentionMode.FULL:
                actual_digest = fingerprint(observation.output, namespace="observation-output")
                if actual_digest != observation.output_digest:
                    message = (
                        "adapter returned an invalid output digest for case "
                        f"{observation.case_id!r}"
                    )
                    raise RunnerContractError(message)

        actual_ids = set(by_id)
        missing = requested_ids - actual_ids
        unexpected = actual_ids - requested_ids
        if duplicates or missing or unexpected:
            details: list[str] = []
            if duplicates:
                details.append(f"duplicate={sorted(duplicates)!r}")
            if missing:
                details.append(f"missing={sorted(missing)!r}")
            if unexpected:
                details.append(f"unexpected={sorted(unexpected)!r}")
            raise RunnerContractError("adapter violated case pairing: " + ", ".join(details))
        return by_id
