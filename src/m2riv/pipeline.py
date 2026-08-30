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
    GateRule,
    GateStatus,
    MetricDirection,
    MetricEvidence,
    MultipleComparisonMethod,
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


@dataclass(frozen=True, slots=True)
class _MetricSamples:
    baseline: tuple[float, ...]
    candidate: tuple[float, ...]
    observations: tuple[EvidenceRef, ...]


@dataclass(frozen=True, slots=True)
class _ReportEvidence:
    manifest: EvidenceManifest | None
    manifest_ref: EvidenceManifestRef | None
    entries: dict[str, EvidenceRef]
    metric_set_ids: dict[str, str]
    critical_set_ids: dict[str, str]


def _status(status: GateStatus) -> MCRStatus:
    return {
        GateStatus.PASS: MCRStatus.PASS,
        GateStatus.WARN: MCRStatus.WARN,
        GateStatus.INSUFFICIENT_POWER: MCRStatus.INSUFFICIENT_POWER,
        GateStatus.BLOCK: MCRStatus.BLOCK,
        GateStatus.ERROR: MCRStatus.ERROR,
    }[status]


def _observation_ref(observation_id: str, retention: RetentionMode) -> EvidenceRef:
    return EvidenceRef(
        id=observation_id,
        kind="observation",
        redacted=retention is not RetentionMode.FULL,
    )


def _collect_metric_samples(
    metric: PairedMetric,
    declaration: PlannedMetric,
    pairs: Sequence[PairedCaseResult],
) -> _MetricSamples:
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
            baseline_value, candidate_value = (float(value) for value in sample)
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
                _observation_ref(pair.baseline.id, pair.baseline.retention),
                _observation_ref(pair.candidate.id, pair.candidate.retention),
            )
        )
    return _MetricSamples(tuple(baseline), tuple(candidate), tuple(observations))


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
    additional_confidence_levels: Sequence[float] = (),
    threshold: float | None = None,
) -> PairedMetricEvidence | None:
    identity_scope = getattr(metric, "identity_scope", "evidence")
    if identity_scope not in {"evidence", "run"}:
        raise MetricExecutionError(
            f"metric {declaration.base_metric_id!r} has an invalid identity scope"
        )
    checked_identity_scope = cast(Literal["evidence", "run"], identity_scope)
    samples = _collect_metric_samples(metric, declaration, pairs)
    if not samples.baseline:
        return None
    binary_evidence: BinaryPairedEvidence | None = None
    if declaration.binary:
        if any(value not in {0.0, 1.0} for value in samples.baseline + samples.candidate):
            raise MetricExecutionError(
                f"binary metric {declaration.base_metric_id!r} emitted a non-binary value"
            )
        binary_evidence = binary_paired_evidence(
            [bool(value) for value in samples.baseline],
            [bool(value) for value in samples.candidate],
            resamples=resamples,
            seed=seed,
            confidence_level=confidence_level,
            additional_confidence_levels=additional_confidence_levels,
            threshold=threshold,
        )
        estimate = binary_evidence.estimate
    else:
        estimate = paired_bootstrap(
            samples.baseline,
            samples.candidate,
            resamples=resamples,
            seed=seed,
            confidence_level=confidence_level,
            additional_confidence_levels=additional_confidence_levels,
            threshold=threshold,
        )
    return PairedMetricEvidence(
        metric_id=metric_id,
        scope=scope,
        direction=declaration.direction,
        unit=declaration.unit,
        identity_scope=checked_identity_scope,
        estimate=estimate,
        binary_evidence=binary_evidence,
        observations=samples.observations,
    )


def _metric_groups(
    declaration: PlannedMetric,
    pairs: Sequence[PairedCaseResult],
    slice_keys: Sequence[str],
) -> tuple[tuple[str, str, Sequence[PairedCaseResult]], ...]:
    groups: list[tuple[str, str, Sequence[PairedCaseResult]]] = [
        (declaration.base_metric_id, "overall", pairs)
    ]
    for slice_key in slice_keys:
        values = sorted(
            {pair.case.slices[slice_key] for pair in pairs if slice_key in pair.case.slices}
        )
        groups.extend(
            (
                f"{declaration.base_metric_id}@{slice_key}={value}",
                f"slice:{slice_key}={value}",
                tuple(pair for pair in pairs if pair.case.slices.get(slice_key) == value),
            )
            for value in values
        )
    return tuple(groups)


def _analyze_metrics(
    plan: CompiledReleasePlan,
    policy: GatePolicy,
    metrics: Sequence[PairedMetric],
    run: PairedRunResult,
    slice_keys: Sequence[str],
    *,
    resamples: int,
    seed: int,
    confidence_level: float,
) -> tuple[PairedMetricEvidence, ...]:
    declarations = tuple(metric for metric in plan.metrics if metric.scope == "overall")
    if len(declarations) != len(metrics):
        raise AssertionError("compiled plan lost a declared base metric")

    rules_by_metric = {rule.metric: rule for rule in policy.rules}
    family_size = len(policy.rules)
    if policy.multiple_comparison_method is MultipleComparisonMethod.HOLM_BONFERRONI:
        required_levels = tuple(
            1.0 - policy.familywise_alpha / denominator
            for denominator in range(family_size, 0, -1)
        )
    else:
        required_levels = (1.0 - policy.familywise_alpha,)

    analyzed: list[PairedMetricEvidence] = []
    for metric, declaration in zip(metrics, declarations, strict=True):
        for metric_id, scope, pairs in _metric_groups(declaration, run.cases, slice_keys):
            rule: GateRule | None = rules_by_metric.get(metric_id)
            additional_levels = tuple(
                level
                for level in required_levels
                if not math.isclose(level, confidence_level, rel_tol=0.0, abs_tol=1e-12)
            )
            threshold = None
            if rule is not None:
                threshold = (
                    -rule.margin
                    if rule.direction is MetricDirection.HIGHER_IS_BETTER
                    else rule.margin
                )
            evidence = _analyze_group(
                metric,
                declaration,
                metric_id,
                scope,
                pairs,
                resamples=resamples,
                seed=seed,
                confidence_level=confidence_level,
                additional_confidence_levels=additional_levels,
                threshold=threshold,
            )
            if evidence is not None:
                analyzed.append(evidence)
    return tuple(analyzed)


def _critical_failures(run: PairedRunResult) -> tuple[str, ...]:
    return tuple(
        pair.case_id
        for pair in run.cases
        if pair.case.critical and pair.candidate.output != pair.case.expected
    )


def _record_evidence(entries: dict[str, EvidenceRef], reference: EvidenceRef) -> None:
    existing = entries.get(reference.id)
    if existing is not None and existing != reference:
        raise ValueError("evidence id is associated with conflicting records")
    entries[reference.id] = reference


def _report_evidence(
    run: PairedRunResult,
    metrics: Sequence[PairedMetricEvidence],
    gate: GateDecision,
) -> _ReportEvidence:
    sets: dict[str, EvidenceSet] = {}
    entries: dict[str, EvidenceRef] = {}
    metric_set_ids: dict[str, str] = {}
    for metric in metrics:
        evidence_set = create_evidence_set(metric.observations)
        sets.setdefault(evidence_set.id, evidence_set)
        metric_set_ids[metric.metric_id] = evidence_set.id
        for observation in metric.observations:
            _record_evidence(entries, observation)

    cases_by_id = {pair.case_id: pair for pair in run.cases}
    critical_set_ids: dict[str, str] = {}
    for case_id in gate.critical_failures:
        pair = cases_by_id[case_id]
        references = (
            _observation_ref(pair.baseline.id, pair.baseline.retention),
            _observation_ref(pair.candidate.id, pair.candidate.retention),
        )
        evidence_set = create_evidence_set(references)
        sets.setdefault(evidence_set.id, evidence_set)
        critical_set_ids[case_id] = evidence_set.id
        for reference in references:
            _record_evidence(entries, reference)

    manifest = (
        create_evidence_manifest(tuple(entries.values()), tuple(sets.values())) if sets else None
    )
    manifest_ref = (
        EvidenceManifestRef(
            id=manifest.id,
            evidence_count=len(manifest.evidence),
            set_count=len(manifest.sets),
        )
        if manifest is not None
        else None
    )
    return _ReportEvidence(
        manifest=manifest,
        manifest_ref=manifest_ref,
        entries=entries,
        metric_set_ids=metric_set_ids,
        critical_set_ids=critical_set_ids,
    )


def _report_findings(gate: GateDecision, evidence: _ReportEvidence) -> tuple[MCRFinding, ...]:
    findings = [
        MCRFinding(
            rule_id=decision.rule_id,
            metric_id=decision.metric,
            status=_status(decision.status),
            message=decision.reason,
            evidence_set_id=evidence.metric_set_ids.get(decision.metric),
            confidence_level=decision.confidence_level,
            interval_lower=decision.confidence_low,
            interval_upper=decision.confidence_high,
            raw_p_value=decision.raw_p_value,
            adjusted_p_value=decision.adjusted_p_value,
            effective_alpha=decision.effective_alpha,
            minimum_detectable_effect=decision.minimum_detectable_effect,
            target_power=decision.target_power,
        )
        for decision in gate.rule_decisions
    ]
    findings.extend(
        MCRFinding(
            rule_id="critical-any-failure",
            status=MCRStatus.BLOCK,
            message=f"critical case failed: {case_id}",
            evidence_set_id=evidence.critical_set_ids[case_id],
        )
        for case_id in gate.critical_failures
    )
    return tuple(findings)


def _report_metrics(
    metrics: Sequence[PairedMetricEvidence], evidence: _ReportEvidence
) -> tuple[MCRMetric, ...]:
    return tuple(
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
            evidence_set_id=evidence.metric_set_ids[metric.metric_id],
            identity_scope=metric.identity_scope,
        )
        for metric in metrics
    )


def _supplemental_evidence(
    additional: Sequence[EvidenceRef], retained: Mapping[str, EvidenceRef]
) -> tuple[EvidenceRef, ...]:
    supplemental: dict[str, EvidenceRef] = {}
    for reference in additional:
        existing = retained.get(reference.id)
        if existing is not None and existing != reference:
            raise ValueError("evidence id is associated with conflicting records")
        if existing is not None:
            continue
        conflicting = supplemental.get(reference.id)
        if conflicting is not None and conflicting != reference:
            raise ValueError("evidence id is associated with conflicting records")
        supplemental[reference.id] = reference
    return tuple(supplemental.values())


def _report_executions(run: PairedRunResult) -> tuple[MCRExecution, MCRExecution]:
    return (
        MCRExecution(
            role="baseline",
            executor_id=run.baseline_execution.descriptor.executor_id,
            executor_version=run.baseline_execution.descriptor.version,
            config_fingerprint=run.baseline_execution.descriptor.config_fingerprint,
            runtime_profile=run.baseline_snapshot.runtime_profile,
            capabilities=run.baseline_execution.descriptor.capabilities,
            requested_cases=run.baseline_execution.requested_cases,
            returned_observations=run.baseline_execution.returned_observations,
            cache_hits=sum(case.baseline_cache_hit for case in run.cases),
        ),
        MCRExecution(
            role="candidate",
            executor_id=run.candidate_execution.descriptor.executor_id,
            executor_version=run.candidate_execution.descriptor.version,
            config_fingerprint=run.candidate_execution.descriptor.config_fingerprint,
            runtime_profile=run.candidate_snapshot.runtime_profile,
            capabilities=run.candidate_execution.descriptor.capabilities,
            requested_cases=run.candidate_execution.requested_cases,
            returned_observations=run.candidate_execution.returned_observations,
            cache_hits=sum(case.candidate_cache_hit for case in run.cases),
        ),
    )


def _report_limitations(run: PairedRunResult) -> tuple[str, str]:
    cache_limitation = (
        "Cache entries used a process-local HMAC key; no cache evidence was trusted "
        "across processes."
        if run.cache_authentication == "run-local-hmac"
        else "Shared cache entries were HMAC-authenticated with MERRIV_CACHE_KEY; this "
        "authenticates cache writers, not the MCR producer."
    )
    return (
        "Metrics are paired over observed cases; this is not a general safety certification.",
        cache_limitation,
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

    metric_evidence = _analyze_metrics(
        plan,
        policy,
        declared_metrics,
        run,
        slice_keys,
        resamples=resamples,
        seed=runtime_profile.seed,
        confidence_level=confidence_level,
    )
    gate = evaluate_gate(
        policy,
        GateEvaluation(
            evidence=tuple(
                MetricEvidence(metric=metric.metric_id, estimate=metric.estimate)
                for metric in metric_evidence
            ),
            critical_failures=_critical_failures(run),
        ),
    )
    report_evidence = _report_evidence(run, metric_evidence, gate)
    report = create_report(
        baseline_snapshot_id=run.baseline_snapshot.id,
        candidate_snapshot_id=run.candidate_snapshot.id,
        release_plan_id=plan.id,
        executions=_report_executions(run),
        metrics=_report_metrics(metric_evidence, report_evidence),
        decision=MCRDecision(
            status=_status(gate.status),
            allowed=(
                gate.status is GateStatus.PASS
                or (gate.status is GateStatus.WARN and policy.allow_warn)
            ),
            findings=_report_findings(gate, report_evidence),
            multiple_comparison_method=gate.multiple_comparison_method.value,
            familywise_alpha=gate.familywise_alpha,
            family_size=gate.family_size,
            target_power=gate.target_power,
        ),
        evidence_manifest=report_evidence.manifest_ref,
        evidence=_supplemental_evidence(
            additional_evidence,
            report_evidence.entries,
        ),
        limitations=_report_limitations(run),
    )
    return ReleaseComparison(
        plan=plan,
        run=run,
        metrics=metric_evidence,
        gate=gate,
        report=report,
        evidence_manifest=report_evidence.manifest,
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
