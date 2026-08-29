"""Portable release policy contracts and their deterministic evaluator."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from m2riv.stats import PairedEstimate

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

    PASS = "pass"
    WARN = "warn"
    BLOCK = "block"
    ERROR = "error"


class MetricDirection(StrEnum):
    """Whether larger or smaller metric values are preferable."""

    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


class GateRule(GateContract):
    """A non-inferiority rule evaluated against the entire confidence interval."""

    rule_id: Identifier
    metric: Identifier
    margin: Annotated[float, Field(ge=0.0)]
    direction: MetricDirection = MetricDirection.HIGHER_IS_BETTER
    min_pairs: Annotated[int, Field(ge=1)] = 30
    block_on_violation: bool = True


class GatePolicy(GateContract):
    """A versioned collection of release rules."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    policy_id: Identifier
    rules: tuple[GateRule, ...] = Field(min_length=1)
    insufficient_evidence_status: Literal[GateStatus.WARN, GateStatus.ERROR] = GateStatus.WARN
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
    margin: float
    n_pairs: int | None = None


class GateDecision(GateContract):
    """Final release outcome with all constituent decisions retained."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    policy_id: Identifier
    status: GateStatus
    rule_decisions: tuple[RuleDecision, ...]
    critical_failures: tuple[Identifier, ...] = ()
    summary: Identifier


def _rule_decision(
    rule: GateRule,
    evidence: MetricEvidence,
    insufficient_status: GateStatus,
) -> RuleDecision:
    estimate = evidence.estimate
    interval = estimate.confidence_interval
    if estimate.n_pairs < rule.min_pairs:
        return _decision_from_estimate(
            rule,
            estimate,
            insufficient_status,
            f"insufficient evidence: {estimate.n_pairs} pairs; requires {rule.min_pairs}",
        )

    if rule.direction is MetricDirection.HIGHER_IS_BETTER:
        passes = interval.low >= -rule.margin
        violates = interval.high < -rule.margin
    else:
        passes = interval.high <= rule.margin
        violates = interval.low > rule.margin

    if passes:
        return _decision_from_estimate(
            rule,
            estimate,
            GateStatus.PASS,
            "the full confidence interval satisfies the non-inferiority margin",
        )
    if violates:
        status = GateStatus.BLOCK if rule.block_on_violation else GateStatus.WARN
        return _decision_from_estimate(
            rule,
            estimate,
            status,
            "the full confidence interval violates the non-inferiority margin",
        )
    return _decision_from_estimate(
        rule,
        estimate,
        GateStatus.WARN,
        "uncertain: the confidence interval crosses the non-inferiority margin",
    )


def _decision_from_estimate(
    rule: GateRule,
    estimate: PairedEstimate,
    status: GateStatus,
    reason: str,
) -> RuleDecision:
    interval = estimate.confidence_interval
    return RuleDecision(
        rule_id=rule.rule_id,
        metric=rule.metric,
        status=status,
        reason=reason,
        effect=estimate.effect,
        confidence_low=interval.low,
        confidence_high=interval.high,
        margin=rule.margin,
        n_pairs=estimate.n_pairs,
    )


def _aggregate_status(decisions: tuple[RuleDecision, ...]) -> GateStatus:
    statuses = {decision.status for decision in decisions}
    # ERROR denotes an invalid/incomplete evaluation, while BLOCK denotes valid
    # evidence against release. Preserve ERROR if both happen so automation cannot
    # mistake a broken evaluation for a fully evaluated policy violation.
    for status in (GateStatus.ERROR, GateStatus.BLOCK, GateStatus.WARN, GateStatus.PASS):
        if status in statuses:
            return status
    return GateStatus.ERROR


def evaluate_gate(policy: GatePolicy, evaluation: GateEvaluation) -> GateDecision:
    """Evaluate non-inferiority and critical safety evidence.

    Missing metrics are ERROR because a policy could not be evaluated. Evidence
    below ``min_pairs`` is never PASS and follows the policy's explicit WARN/ERROR
    choice. A confidence interval crossing the margin is always WARN. A candidate
    critical failure directly BLOCKs when the policy enables the safety override.
    """

    evidence_by_metric = {item.metric: item for item in evaluation.evidence}
    decisions: list[RuleDecision] = []
    for rule in policy.rules:
        evidence = evidence_by_metric.get(rule.metric)
        if evidence is None:
            decisions.append(
                RuleDecision(
                    rule_id=rule.rule_id,
                    metric=rule.metric,
                    status=GateStatus.ERROR,
                    reason="required metric evidence is missing",
                    margin=rule.margin,
                )
            )
            continue
        decisions.append(_rule_decision(rule, evidence, policy.insufficient_evidence_status))

    rule_decisions = tuple(decisions)
    if evaluation.critical_failures and policy.block_on_any_critical_failure:
        status = GateStatus.BLOCK
        summary = (
            f"blocked by {len(evaluation.critical_failures)} critical failure(s); "
            f"rule status was {_aggregate_status(rule_decisions).value}"
        )
    else:
        status = _aggregate_status(rule_decisions)
        summary = f"{status.value}: evaluated {len(rule_decisions)} release rule(s)"
    return GateDecision(
        policy_id=policy.policy_id,
        status=status,
        rule_decisions=rule_decisions,
        critical_failures=evaluation.critical_failures,
        summary=summary,
    )
