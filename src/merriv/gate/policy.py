"""Portable release policy contracts and their deterministic evaluator."""

from __future__ import annotations

import math
from enum import StrEnum
from statistics import NormalDist
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from merriv.stats import ConfidenceInterval, PairedEstimate

Identifier = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]


class GateContract(BaseModel):
    """Strict and immutable gate data contract."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        use_enum_values=False,
        allow_inf_nan=False,
    )


class GateStatus(StrEnum):
    """Ordered release decision states."""

    PASS = "pass"  # nosec B105  # noqa: S105 - release status, not a credential
    WARN = "warn"
    INSUFFICIENT_POWER = "insufficient_power"
    BLOCK = "block"
    ERROR = "error"


class MetricDirection(StrEnum):
    """Whether larger or smaller metric values are preferable."""

    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


class MultipleComparisonMethod(StrEnum):
    """Policy-wide correction applied to the complete rule family."""

    NONE = "none"
    HOLM_BONFERRONI = "holm-bonferroni"


class GateRule(GateContract):
    """A non-inferiority rule evaluated against the entire confidence interval."""

    rule_id: Identifier
    metric: Identifier
    margin: Annotated[float, Field(ge=0.0)]
    direction: MetricDirection = MetricDirection.HIGHER_IS_BETTER
    # Retained for policies that have a cohort floor for non-statistical reasons.
    # Power-sensitive policies should set max_mde instead of guessing a sample count.
    min_pairs: Annotated[int | None, Field(ge=1)] = None
    max_mde: Annotated[float | None, Field(gt=0.0)] = None
    planned_difference_stddev: Annotated[float | None, Field(gt=0.0)] = None
    block_on_violation: bool = True

    @model_validator(mode="after")
    def prospective_power_gate_requires_planned_variance(self) -> GateRule:
        if self.max_mde is not None and self.planned_difference_stddev is None:
            raise ValueError(
                "max_mde requires a prospectively specified planned_difference_stddev"
            )
        return self


class GatePolicy(GateContract):
    """A versioned collection of release rules."""

    schema_version: Literal["1.0.0", "1.1.0"] = "1.1.0"
    policy_id: Identifier
    rules: tuple[GateRule, ...] = Field(min_length=1)
    multiple_comparison_method: MultipleComparisonMethod = (
        MultipleComparisonMethod.HOLM_BONFERRONI
    )
    familywise_alpha: Annotated[float, Field(gt=0.0, lt=1.0)] = 0.05
    target_power: Annotated[float, Field(gt=0.5, lt=1.0)] = 0.8
    insufficient_evidence_status: Literal[
        GateStatus.INSUFFICIENT_POWER,
        GateStatus.WARN,
        GateStatus.ERROR,
    ] = GateStatus.INSUFFICIENT_POWER
    allow_warn: bool = False
    block_on_any_critical_failure: bool = True

    @model_validator(mode="after")
    def unique_rules_and_metrics(self) -> GatePolicy:
        rule_ids = [rule.rule_id for rule in self.rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("rule_id values must be unique")
        metrics = [rule.metric for rule in self.rules]
        if len(metrics) != len(set(metrics)):
            raise ValueError("each metric may be governed by only one rule")
        if self.schema_version == "1.0.0" and any(
            rule.planned_difference_stddev is not None for rule in self.rules
        ):
            raise ValueError(
                "planned_difference_stddev requires GatePolicy schema_version 1.1.0"
            )
        return self


class MetricEvidence(GateContract):
    """Statistical evidence associated with a named release metric."""

    metric: Identifier
    estimate: PairedEstimate


class GateEvaluation(GateContract):
    """All evidence presented to a policy for one candidate release."""

    evidence: tuple[MetricEvidence, ...] = ()
    critical_failures: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def unique_metrics(self) -> GateEvaluation:
        metrics = [item.metric for item in self.evidence]
        if len(metrics) != len(set(metrics)):
            raise ValueError("metric evidence must be unique")
        return self


class RuleDecision(GateContract):
    """Auditable outcome of exactly one policy rule."""

    rule_id: Identifier
    metric: Identifier
    status: GateStatus
    reason: Identifier
    effect: float | None = None
    confidence_low: float | None = None
    confidence_high: float | None = None
    confidence_level: float | None = None
    margin: float
    n_pairs: int | None = None
    raw_p_value: Annotated[float | None, Field(ge=0.0, le=1.0)] = None
    adjusted_p_value: Annotated[float | None, Field(ge=0.0, le=1.0)] = None
    effective_alpha: Annotated[float | None, Field(gt=0.0, lt=1.0)] = None
    minimum_detectable_effect: Annotated[float | None, Field(ge=0.0)] = None
    target_power: Annotated[float | None, Field(gt=0.5, lt=1.0)] = None


class GateDecision(GateContract):
    """Final release outcome with all constituent decisions retained."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    policy_id: Identifier
    status: GateStatus
    rule_decisions: tuple[RuleDecision, ...]
    multiple_comparison_method: MultipleComparisonMethod
    familywise_alpha: Annotated[float, Field(gt=0.0, lt=1.0)]
    family_size: Annotated[int, Field(ge=1)]
    target_power: Annotated[float, Field(gt=0.5, lt=1.0)]
    critical_failures: tuple[Identifier, ...] = ()
    summary: Identifier


def _threshold(rule: GateRule) -> float:
    if rule.direction is MetricDirection.HIGHER_IS_BETTER:
        return -rule.margin
    return rule.margin


def _interval_at(estimate: PairedEstimate, confidence_level: float) -> ConfidenceInterval | None:
    intervals = (estimate.confidence_interval, *estimate.additional_confidence_intervals)
    return next(
        (
            interval
            for interval in intervals
            if math.isclose(
                interval.confidence_level,
                confidence_level,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        ),
        None,
    )


def _minimum_detectable_effect(
    estimate: PairedEstimate,
    *,
    alpha: float,
    target_power: float,
    planned_difference_stddev: float | None,
) -> float | None:
    """Prospective or diagnostic MDE using a normal approximation."""

    difference_stddev = planned_difference_stddev or estimate.difference_stddev
    if difference_stddev is None or estimate.n_pairs < 2:
        return None
    normal = NormalDist()
    critical = normal.inv_cdf(1.0 - alpha / 2.0)
    power_quantile = normal.inv_cdf(target_power)
    return (critical + power_quantile) * difference_stddev / math.sqrt(estimate.n_pairs)


def _decision_from_estimate(
    rule: GateRule,
    estimate: PairedEstimate,
    status: GateStatus,
    reason: str,
    *,
    interval: ConfidenceInterval,
    raw_p_value: float | None,
    adjusted_p_value: float | None,
    effective_alpha: float,
    minimum_detectable_effect: float | None,
    target_power: float,
) -> RuleDecision:
    return RuleDecision(
        rule_id=rule.rule_id,
        metric=rule.metric,
        status=status,
        reason=reason,
        effect=estimate.effect,
        confidence_low=interval.low,
        confidence_high=interval.high,
        confidence_level=interval.confidence_level,
        margin=rule.margin,
        n_pairs=estimate.n_pairs,
        raw_p_value=raw_p_value,
        adjusted_p_value=adjusted_p_value,
        effective_alpha=effective_alpha,
        minimum_detectable_effect=minimum_detectable_effect,
        target_power=target_power,
    )


def _insufficient_decision(
    rule: GateRule,
    estimate: PairedEstimate,
    policy: GatePolicy,
    *,
    minimum_detectable_effect: float | None,
    reason: str,
    status: GateStatus | None = None,
) -> RuleDecision:
    return _decision_from_estimate(
        rule,
        estimate,
        status or policy.insufficient_evidence_status,
        reason,
        interval=estimate.confidence_interval,
        raw_p_value=(
            estimate.hypothesis_test.p_value
            if estimate.hypothesis_test is not None
            else None
        ),
        adjusted_p_value=None,
        effective_alpha=policy.familywise_alpha / len(policy.rules),
        minimum_detectable_effect=minimum_detectable_effect,
        target_power=policy.target_power,
    )


def _evaluate_interval(
    rule: GateRule,
    estimate: PairedEstimate,
    *,
    interval: ConfidenceInterval,
    raw_p_value: float | None,
    adjusted_p_value: float | None,
    effective_alpha: float,
    minimum_detectable_effect: float | None,
    target_power: float,
    statistically_decisive: bool,
) -> RuleDecision:
    threshold = _threshold(rule)
    method_suffix = (
        f"; hypothesis test: {estimate.hypothesis_test.method}"
        if estimate.hypothesis_test is not None
        else ""
    )
    if rule.direction is MetricDirection.HIGHER_IS_BETTER:
        passes = interval.low >= threshold
        violates = interval.high < threshold
    else:
        passes = interval.high <= threshold
        violates = interval.low > threshold

    if passes and statistically_decisive:
        return _decision_from_estimate(
            rule,
            estimate,
            GateStatus.PASS,
            "the full multiplicity-adjusted confidence interval satisfies the "
            f"non-inferiority margin{method_suffix}",
            interval=interval,
            raw_p_value=raw_p_value,
            adjusted_p_value=adjusted_p_value,
            effective_alpha=effective_alpha,
            minimum_detectable_effect=minimum_detectable_effect,
            target_power=target_power,
        )
    if violates and statistically_decisive:
        status = GateStatus.BLOCK if rule.block_on_violation else GateStatus.WARN
        return _decision_from_estimate(
            rule,
            estimate,
            status,
            "the full multiplicity-adjusted confidence interval violates the "
            f"non-inferiority margin{method_suffix}",
            interval=interval,
            raw_p_value=raw_p_value,
            adjusted_p_value=adjusted_p_value,
            effective_alpha=effective_alpha,
            minimum_detectable_effect=minimum_detectable_effect,
            target_power=target_power,
        )
    return _decision_from_estimate(
        rule,
        estimate,
        GateStatus.WARN,
        "uncertain after multiplicity correction: the adjusted confidence interval "
        "crosses the non-inferiority margin or the Holm hypothesis was not rejected"
        f"{method_suffix}",
        interval=interval,
        raw_p_value=raw_p_value,
        adjusted_p_value=adjusted_p_value,
        effective_alpha=effective_alpha,
        minimum_detectable_effect=minimum_detectable_effect,
        target_power=target_power,
    )


def _aggregate_status(decisions: tuple[RuleDecision, ...]) -> GateStatus:
    statuses = {decision.status for decision in decisions}
    for status in (
        GateStatus.ERROR,
        GateStatus.BLOCK,
        GateStatus.INSUFFICIENT_POWER,
        GateStatus.WARN,
        GateStatus.PASS,
    ):
        if status in statuses:
            return status
    return GateStatus.ERROR


def evaluate_gate(policy: GatePolicy, evaluation: GateEvaluation) -> GateDecision:
    """Evaluate a complete non-inferiority family and critical safety evidence.

    Holm-Bonferroni is applied to formal two-sided paired hypothesis tests.
    A decisive rule still compares the complete interval at its Holm step alpha;
    point estimates alone never PASS or BLOCK. Power uses a prospectively declared
    paired-difference spread when supplied; the observed spread is diagnostic only.
    Rules with an explicit ``max_mde`` therefore require
    ``planned_difference_stddev`` and fail closed when that detectable effect is too
    coarse for the policy.
    """

    evidence_by_metric = {item.metric: item for item in evaluation.evidence}
    family_size = len(policy.rules)
    planning_alpha = (
        policy.familywise_alpha / family_size
        if policy.multiple_comparison_method is MultipleComparisonMethod.HOLM_BONFERRONI
        else policy.familywise_alpha
    )

    estimates: dict[str, PairedEstimate] = {}
    mdes: dict[str, float | None] = {}
    preliminary: dict[str, RuleDecision] = {}
    raw_p_values: dict[str, float] = {}
    for rule in policy.rules:
        evidence = evidence_by_metric.get(rule.metric)
        if evidence is None:
            preliminary[rule.rule_id] = RuleDecision(
                rule_id=rule.rule_id,
                metric=rule.metric,
                status=GateStatus.ERROR,
                reason="required metric evidence is missing",
                margin=rule.margin,
            )
            continue

        estimate = evidence.estimate
        estimates[rule.rule_id] = estimate
        mde = _minimum_detectable_effect(
            estimate,
            alpha=planning_alpha,
            target_power=policy.target_power,
            planned_difference_stddev=rule.planned_difference_stddev,
        )
        mdes[rule.rule_id] = mde
        if rule.min_pairs is not None and estimate.n_pairs < rule.min_pairs:
            preliminary[rule.rule_id] = _insufficient_decision(
                rule,
                estimate,
                policy,
                minimum_detectable_effect=mde,
                reason=(
                    f"insufficient evidence: {estimate.n_pairs} pairs; "
                    f"requires {rule.min_pairs}"
                ),
            )
            continue
        if rule.max_mde is not None and (mde is None or mde > rule.max_mde):
            rendered_mde = "undefined" if mde is None else f"{mde:.6g}"
            preliminary[rule.rule_id] = _insufficient_decision(
                rule,
                estimate,
                policy,
                minimum_detectable_effect=mde,
                reason=(
                    f"insufficient power: planned-design MDE {rendered_mde} exceeds "
                    "the policy maximum "
                    f"{rule.max_mde:.6g} at power {policy.target_power:.3g}"
                ),
                status=GateStatus.INSUFFICIENT_POWER,
            )
            continue

        hypothesis_test = estimate.hypothesis_test
        if policy.multiple_comparison_method is MultipleComparisonMethod.HOLM_BONFERRONI:
            if family_size == 1:
                continue
            if hypothesis_test is None or not math.isclose(
                hypothesis_test.null_value,
                _threshold(rule),
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                preliminary[rule.rule_id] = RuleDecision(
                    rule_id=rule.rule_id,
                    metric=rule.metric,
                    status=GateStatus.ERROR,
                    reason=(
                        "Holm-Bonferroni requires formal paired hypothesis-test evidence "
                        "at the rule margin"
                    ),
                    margin=rule.margin,
                    n_pairs=estimate.n_pairs,
                    minimum_detectable_effect=mde,
                    target_power=policy.target_power,
                )
                continue
            raw_p_values[rule.rule_id] = hypothesis_test.p_value

    adjustments: dict[str, tuple[float, float, float]] = {}
    if policy.multiple_comparison_method is MultipleComparisonMethod.HOLM_BONFERRONI:
        ordered = sorted(raw_p_values.items(), key=lambda item: (item[1], item[0]))
        running_adjusted = 0.0
        for rank, (rule_id, ordered_p_value) in enumerate(ordered, start=1):
            effective_alpha = policy.familywise_alpha / (family_size - rank + 1)
            running_adjusted = max(
                running_adjusted,
                min(1.0, (family_size - rank + 1) * ordered_p_value),
            )
            adjustments[rule_id] = (ordered_p_value, running_adjusted, effective_alpha)

    decisions: list[RuleDecision] = []
    for rule in policy.rules:
        if rule.rule_id in preliminary:
            decisions.append(preliminary[rule.rule_id])
            continue
        estimate = estimates[rule.rule_id]
        mde = mdes[rule.rule_id]
        if (
            policy.multiple_comparison_method is MultipleComparisonMethod.NONE
            or family_size == 1
        ):
            effective_alpha = policy.familywise_alpha
            raw_p_value = (
                estimate.hypothesis_test.p_value
                if estimate.hypothesis_test is not None
                else None
            )
            adjusted_p_value = raw_p_value
            decisive = True
        else:
            raw_p_value, adjusted_p_value, effective_alpha = adjustments[rule.rule_id]
            decisive = adjusted_p_value <= policy.familywise_alpha

        confidence_level = 1.0 - effective_alpha
        interval = _interval_at(estimate, confidence_level)
        if interval is None:
            decisions.append(
                RuleDecision(
                    rule_id=rule.rule_id,
                    metric=rule.metric,
                    status=GateStatus.ERROR,
                    reason=(
                        "statistical evidence is missing the confidence interval required "
                        "by the policy-wide correction"
                    ),
                    effect=estimate.effect,
                    margin=rule.margin,
                    n_pairs=estimate.n_pairs,
                    raw_p_value=raw_p_value,
                    adjusted_p_value=adjusted_p_value,
                    effective_alpha=effective_alpha,
                    minimum_detectable_effect=mde,
                    target_power=policy.target_power,
                )
            )
            continue
        decisions.append(
            _evaluate_interval(
                rule,
                estimate,
                interval=interval,
                raw_p_value=raw_p_value,
                adjusted_p_value=adjusted_p_value,
                effective_alpha=effective_alpha,
                minimum_detectable_effect=mde,
                target_power=policy.target_power,
                statistically_decisive=decisive,
            )
        )

    rule_decisions = tuple(decisions)
    if evaluation.critical_failures and policy.block_on_any_critical_failure:
        status = GateStatus.BLOCK
        summary = (
            f"blocked by {len(evaluation.critical_failures)} critical failure(s); "
            f"rule status was {_aggregate_status(rule_decisions).value}"
        )
    else:
        status = _aggregate_status(rule_decisions)
        summary = (
            f"{status.value}: evaluated {len(rule_decisions)} release rule(s) as one "
            f"family at alpha={policy.familywise_alpha:g}"
        )
    return GateDecision(
        policy_id=policy.policy_id,
        status=status,
        rule_decisions=rule_decisions,
        multiple_comparison_method=policy.multiple_comparison_method,
        familywise_alpha=policy.familywise_alpha,
        family_size=family_size,
        target_power=policy.target_power,
        critical_failures=evaluation.critical_failures,
        summary=summary,
    )
