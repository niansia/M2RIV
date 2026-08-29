"""First vertical release-comparison pipeline built on the evidence kernel."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, cast

from m2riv.adapters import ModelAdapter
from m2riv.core.models import (
    EvalCase,
    EvidenceRef,
    PluginRecord,
    RetentionMode,
    RuntimeProfile,
)
from m2riv.engine import ObservationCache, PairedCaseResult, PairedRunner, PairedRunResult
from m2riv.execution import ExecutionBackend
from m2riv.gate import (
    GateDecision,
    GateEvaluation,
    GatePolicy,
    GateStatus,
    MetricDirection,
    MetricEvidence,
    evaluate_gate,
)
from m2riv.metrics import PairedMetric
from m2riv.planning import CompiledReleasePlan, compile_release_plan
from m2riv.planning.models import PlannedMetric
from m2riv.plugins import builtin_metric_registry
from m2riv.reports import (
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
from m2riv.stats import (
    BinaryPairedEvidence,
    PairedEstimate,
    binary_paired_evidence,
    paired_bootstrap,
)


@dataclass(frozen=True, slots=True)
class PairedMetricEvidence:
    metric_id: str
    scope: str
    direction: MetricDirection
    unit: str
    identity_scope: Literal["evidence", "run"]
    estimate: PairedEstimate
    binary_evidence: BinaryPairedEvidence | None
    observations: tuple[EvidenceRef, ...]


@dataclass(frozen=True, slots=True)
class ReleaseComparison:
    plan: CompiledReleasePlan
    run: PairedRunResult
    metrics: tuple[PairedMetricEvidence, ...]
    gate: GateDecision
    report: ModelChangeReport
    evidence_manifest: EvidenceManifest | None


class MetricExecutionError(ValueError):
    """A metric plugin failed or returned untrustworthy paired samples."""


def _status(status: GateStatus) -> MCRStatus:
    return {
        GateStatus.PASS: MCRStatus.PASS,
        GateStatus.WARN: MCRStatus.WARN,
        GateStatus.BLOCK: MCRStatus.BLOCK,
        GateStatus.ERROR: MCRStatus.ERROR,
    }[status]


def _observation_ref(observation_id: str, retention: RetentionMode) -> EvidenceRef:
    return EvidenceRef(
        id=observation_id,
        kind="observation",
        redacted=retention is not RetentionMode.FULL,
    )


def _analyze_group(
    metric: PairedMetric,
    declaration: PlannedMetric,
    metric_id: str,
    scope: str,
    pairs: Sequence[PairedCaseResult],
    *,
    resamples: int,
    seed: int,
    confidence_level: float,
) -> PairedMetricEvidence | None:
    identity_scope = getattr(metric, "identity_scope", "evidence")
    if identity_scope not in {"evidence", "run"}:
        raise MetricExecutionError(
            f"metric {declaration.base_metric_id!r} has an invalid identity scope"
        )
    checked_identity_scope = cast(Literal["evidence", "run"], identity_scope)
    baseline: list[float] = []
    candidate: list[float] = []
    observations: list[EvidenceRef] = []
    for pair in pairs:
        try:
            sample = metric.sample(pair)
        except Exception:
            raise MetricExecutionError(f"metric {declaration.base_metric_id!r} failed") from None
        if sample is None:
            continue
        if not isinstance(sample, tuple) or len(sample) != 2:
            raise MetricExecutionError(
                f"metric {declaration.base_metric_id!r} returned an invalid paired sample"
            )
        try:
            baseline_value = float(sample[0])
            candidate_value = float(sample[1])
        except (TypeError, ValueError, OverflowError):
            raise MetricExecutionError(
                f"metric {declaration.base_metric_id!r} returned a non-numeric paired sample"
            ) from None
        if not math.isfinite(baseline_value) or not math.isfinite(candidate_value):
            raise MetricExecutionError(
                f"metric {declaration.base_metric_id!r} returned a non-finite paired sample"
            )
        baseline.append(baseline_value)
        candidate.append(candidate_value)
        observations.extend(
            (
                _observation_ref(
                    pair.baseline.id,
                    pair.baseline.retention,
                ),
                _observation_ref(
                    pair.candidate.id,
                    pair.candidate.retention,
                ),
            )
        )
    if not baseline:
        return None
    binary_evidence: BinaryPairedEvidence | None = None
    if declaration.binary:
        if any(value not in {0.0, 1.0} for value in baseline + candidate):
            raise MetricExecutionError(
                f"binary metric {declaration.base_metric_id!r} emitted a non-binary value"
            )
        binary_evidence = binary_paired_evidence(
            [bool(value) for value in baseline],
            [bool(value) for value in candidate],
            resamples=resamples,
            seed=seed,
            confidence_level=confidence_level,
        )
        estimate = binary_evidence.estimate
    else:
        estimate = paired_bootstrap(
            baseline,
            candidate,
            resamples=resamples,
            seed=seed,
            confidence_level=confidence_level,
        )
    return PairedMetricEvidence(
        metric_id=metric_id,
        scope=scope,
        direction=declaration.direction,
        unit=declaration.unit,
        identity_scope=checked_identity_scope,
        estimate=estimate,
        binary_evidence=binary_evidence,
        observations=tuple(observations),
    )


def compare_release(
    *,
    baseline: ModelAdapter,
    candidate: ModelAdapter,
    cases: Sequence[EvalCase],
    policy: GatePolicy,
    cache: ObservationCache,
    profile: RuntimeProfile | None = None,
    slice_keys: Sequence[str] = (),
    baseline_adapter_fingerprint: str,
    candidate_adapter_fingerprint: str,
    metrics: Sequence[PairedMetric],
    metric_plugins: Mapping[str, PluginRecord] | None = None,
    additional_evidence: Sequence[EvidenceRef] = (),
    baseline_executor: ExecutionBackend | None = None,
    candidate_executor: ExecutionBackend | None = None,
    resamples: int = 2_000,
    confidence_level: float = 0.95,
) -> ReleaseComparison:
    """Run adapters once, then evaluate pluggable paired metrics and release policy."""
    runtime_profile = profile or RuntimeProfile()
    declared_metrics = tuple(metrics)
    plan = compile_release_plan(
        policy=policy,
        cases=cases,
        metrics=declared_metrics,
        slice_keys=slice_keys,
        metric_plugins=metric_plugins,
        runtime_profile=runtime_profile,
        resamples=resamples,
        confidence_level=confidence_level,
    )
    run = PairedRunner(
        cache,
        baseline_executor=baseline_executor,
        candidate_executor=candidate_executor,
    ).run(
        baseline,
        candidate,
        cases,
        profile=runtime_profile,
        baseline_adapter_fingerprint=baseline_adapter_fingerprint,
        candidate_adapter_fingerprint=candidate_adapter_fingerprint,
    )

    analyzed: list[PairedMetricEvidence] = []
    base_declarations = tuple(
        planned_metric for planned_metric in plan.metrics if planned_metric.scope == "overall"
    )
    if len(base_declarations) != len(declared_metrics):
        raise AssertionError("compiled plan lost a declared base metric")
    for metric, declaration in zip(declared_metrics, base_declarations, strict=True):
        groups: list[tuple[str, str, Sequence[PairedCaseResult]]] = [
            (declaration.base_metric_id, "overall", run.cases)
        ]
        for slice_key in slice_keys:
            values = sorted(
                {pair.case.slices[slice_key] for pair in run.cases if slice_key in pair.case.slices}
            )
            for value in values:
                groups.append(
                    (
                        f"{declaration.base_metric_id}@{slice_key}={value}",
                        f"slice:{slice_key}={value}",
                        tuple(
                            pair for pair in run.cases if pair.case.slices.get(slice_key) == value
                        ),
                    )
                )
        for metric_id, scope, pairs in groups:
            evidence = _analyze_group(
                metric,
                declaration,
                metric_id,
                scope,
                pairs,
                resamples=resamples,
                seed=runtime_profile.seed,
                confidence_level=confidence_level,
            )
            if evidence is not None:
                analyzed.append(evidence)
    metric_evidence = tuple(analyzed)
    critical_failures = tuple(
        pair.case_id
        for pair in run.cases
        if pair.case.critical and pair.candidate.output != pair.case.expected
    )
    gate = evaluate_gate(
        policy,
        GateEvaluation(
            evidence=tuple(
                MetricEvidence(metric=metric.metric_id, estimate=metric.estimate)
                for metric in metric_evidence
            ),
            critical_failures=critical_failures,
        ),
    )

    evidence_sets: dict[str, EvidenceSet] = {}
    evidence_entries: dict[str, EvidenceRef] = {}
    metric_set_ids: dict[str, str] = {}
    for metric_result in metric_evidence:
        evidence_set = create_evidence_set(metric_result.observations)
        evidence_sets.setdefault(evidence_set.id, evidence_set)
        metric_set_ids[metric_result.metric_id] = evidence_set.id
        for observation in metric_result.observations:
            existing = evidence_entries.get(observation.id)
            if existing is not None and existing != observation:
                raise ValueError("evidence id is associated with conflicting records")
            evidence_entries[observation.id] = observation
    critical_set_ids: dict[str, str] = {}
    for case_id in gate.critical_failures:
        pair = next(item for item in run.cases if item.case_id == case_id)
        references = (
            _observation_ref(pair.baseline.id, pair.baseline.retention),
            _observation_ref(pair.candidate.id, pair.candidate.retention),
        )
        evidence_set = create_evidence_set(references)
        evidence_sets.setdefault(evidence_set.id, evidence_set)
        critical_set_ids[case_id] = evidence_set.id
        for observation in references:
            existing = evidence_entries.get(observation.id)
            if existing is not None and existing != observation:
                raise ValueError("evidence id is associated with conflicting records")
            evidence_entries[observation.id] = observation
    findings = [
        MCRFinding(
            rule_id=decision.rule_id,
            metric_id=decision.metric,
            status=_status(decision.status),
            message=decision.reason,
            evidence_set_id=metric_set_ids.get(decision.metric),
        )
        for decision in gate.rule_decisions
    ]
    findings.extend(
        MCRFinding(
            rule_id="critical-any-failure",
            status=MCRStatus.BLOCK,
            message=f"critical case failed: {case_id}",
            evidence_set_id=critical_set_ids[case_id],
        )
        for case_id in gate.critical_failures
    )
    evidence_manifest = (
        create_evidence_manifest(
            tuple(evidence_entries.values()), tuple(evidence_sets.values())
        )
        if evidence_sets
        else None
    )
    manifest_ref = (
        EvidenceManifestRef(
            id=evidence_manifest.id,
            evidence_count=len(evidence_manifest.evidence),
            set_count=len(evidence_manifest.sets),
        )
        if evidence_manifest is not None
        else None
    )
    mcr_metrics = tuple(
        MCRMetric(
            metric_id=metric.metric_id,
            scope=metric.scope,
            direction=metric.direction.value,
            unit=metric.unit,
            baseline_value=metric.estimate.baseline_mean,
            candidate_value=metric.estimate.candidate_mean,
            delta=metric.estimate.effect,
            confidence_level=metric.estimate.confidence_interval.confidence_level,
            interval_lower=metric.estimate.confidence_interval.low,
            interval_upper=metric.estimate.confidence_interval.high,
            effect_size=metric.estimate.effect_size,
            sample_size=metric.estimate.n_pairs,
            evidence_set_id=metric_set_ids[metric.metric_id],
            identity_scope=metric.identity_scope,
        )
        for metric in metric_evidence
    )
    supplemental_refs: dict[str, EvidenceRef] = {}
    for supplemental in additional_evidence:
        existing = evidence_entries.get(supplemental.id)
        if existing is not None and existing != supplemental:
            raise ValueError("evidence id is associated with conflicting records")
        if existing is None:
            conflicting = supplemental_refs.get(supplemental.id)
            if conflicting is not None and conflicting != supplemental:
                raise ValueError("evidence id is associated with conflicting records")
            supplemental_refs[supplemental.id] = supplemental
    report = create_report(
        baseline_snapshot_id=run.baseline_snapshot.id,
        candidate_snapshot_id=run.candidate_snapshot.id,
        release_plan_id=plan.id,
        executions=(
            MCRExecution(
                role="baseline",
                executor_id=run.baseline_execution.descriptor.executor_id,
                executor_version=run.baseline_execution.descriptor.version,
                config_fingerprint=(run.baseline_execution.descriptor.config_fingerprint),
                capabilities=run.baseline_execution.descriptor.capabilities,
                requested_cases=run.baseline_execution.requested_cases,
                returned_observations=(run.baseline_execution.returned_observations),
                cache_hits=sum(case.baseline_cache_hit for case in run.cases),
            ),
            MCRExecution(
                role="candidate",
                executor_id=run.candidate_execution.descriptor.executor_id,
                executor_version=run.candidate_execution.descriptor.version,
                config_fingerprint=(run.candidate_execution.descriptor.config_fingerprint),
                capabilities=run.candidate_execution.descriptor.capabilities,
                requested_cases=run.candidate_execution.requested_cases,
                returned_observations=(run.candidate_execution.returned_observations),
                cache_hits=sum(case.candidate_cache_hit for case in run.cases),
            ),
        ),
        metrics=mcr_metrics,
        decision=MCRDecision(
            status=_status(gate.status),
            allowed=(
                gate.status is GateStatus.PASS
                or (gate.status is GateStatus.WARN and policy.allow_warn)
            ),
            findings=tuple(findings),
        ),
        evidence_manifest=manifest_ref,
        evidence=tuple(supplemental_refs.values()),
        limitations=(
            "Metrics are paired over observed cases; this is not a general safety certification.",
        ),
    )
    return ReleaseComparison(
        plan=plan,
        run=run,
        metrics=metric_evidence,
        gate=gate,
        report=report,
        evidence_manifest=evidence_manifest,
    )


def compare_exact_match(
    *,
    baseline: ModelAdapter,
    candidate: ModelAdapter,
    cases: Sequence[EvalCase],
    policy: GatePolicy,
    cache: ObservationCache,
    profile: RuntimeProfile | None = None,
    slice_keys: Sequence[str] = (),
    baseline_adapter_fingerprint: str,
    candidate_adapter_fingerprint: str,
    baseline_executor: ExecutionBackend | None = None,
    candidate_executor: ExecutionBackend | None = None,
    additional_evidence: Sequence[EvidenceRef] = (),
    resamples: int = 2_000,
    confidence_level: float = 0.95,
) -> ReleaseComparison:
    """Compatibility wrapper with exact-match quality and optional latency evidence."""
    registry = builtin_metric_registry()
    return compare_release(
        baseline=baseline,
        candidate=candidate,
        cases=cases,
        policy=policy,
        cache=cache,
        profile=profile,
        slice_keys=slice_keys,
        baseline_adapter_fingerprint=baseline_adapter_fingerprint,
        candidate_adapter_fingerprint=candidate_adapter_fingerprint,
        metrics=registry.metrics(),
        metric_plugins=registry.metric_plugin_records(),
        additional_evidence=additional_evidence,
        baseline_executor=baseline_executor,
        candidate_executor=candidate_executor,
        resamples=resamples,
        confidence_level=confidence_level,
    )
