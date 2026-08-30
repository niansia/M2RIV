from __future__ import annotations

import pytest
from pydantic import ValidationError

from merriv.gate import (
    GateEvaluation,
    GatePolicy,
    GateRule,
    GateStatus,
    MetricDirection,
    MetricEvidence,
    evaluate_gate,
)
from merriv.stats import (
    BinaryFlipMatrix,
    ConfidenceInterval,
    PairedEstimate,
    binary_paired_evidence,
    paired_bootstrap,
)


def test_paired_bootstrap_is_deterministic_and_preserves_pairing() -> None:
    baseline = [0.0, 1.0, 2.0, 3.0]
    candidate = [1.0, 2.0, 3.0, 4.0]

    first = paired_bootstrap(baseline, candidate, resamples=500, seed=73)
    second = paired_bootstrap(baseline, candidate, resamples=500, seed=73)

    assert first == second
    assert first.effect == 1.0
    assert first.effect_size is None
    assert first.confidence_interval.low == 1.0
    assert first.confidence_interval.high == 1.0


def test_paired_effect_size_is_standardized_not_a_duplicate_delta() -> None:
    estimate = paired_bootstrap(
        [0.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 2.0, 3.0],
        resamples=100,
    )

    assert estimate.effect == 1.5
    assert estimate.effect_size == pytest.approx(1.161895003862225)


def test_binary_evidence_has_flip_matrix_effect_and_exact_mcnemar() -> None:
    evidence = binary_paired_evidence(
        [True, True, True, False, False, False],
        [True, False, False, True, False, False],
        resamples=500,
        seed=9,
    )

    assert evidence.flips.both_pass == 1
    assert evidence.flips.baseline_only == 2
    assert evidence.flips.candidate_only == 1
    assert evidence.flips.both_fail == 2
    assert evidence.flips.discordant_pairs == 3
    assert evidence.estimate.effect == pytest.approx(-1 / 6)
    assert evidence.mcnemar_exact_p_value == 1.0


def test_mcnemar_evidence_handles_large_suites_without_float_overflow() -> None:
    evidence = binary_paired_evidence(
        [True] * 1_000 + [False] * 1_000,
        [False] * 1_000 + [True] * 1_000,
        resamples=10,
    )

    assert evidence.mcnemar_exact_p_value == 1.0


def _policy(
    *,
    min_pairs: int = 3,
    insufficient: GateStatus = GateStatus.WARN,
    direction: MetricDirection = MetricDirection.HIGHER_IS_BETTER,
) -> GatePolicy:
    return GatePolicy(
        policy_id="release-v1",
        rules=(
            GateRule(
                rule_id="quality-ni",
                metric="quality",
                margin=0.1,
                min_pairs=min_pairs,
                direction=direction,
            ),
        ),
        insufficient_evidence_status=insufficient,
    )


def _evaluation(baseline: list[float], candidate: list[float]) -> GateEvaluation:
    return GateEvaluation(
        evidence=(
            MetricEvidence(
                metric="quality",
                estimate=paired_bootstrap(baseline, candidate, resamples=1_000, seed=5),
            ),
        )
    )


def test_gate_passes_only_when_full_interval_meets_margin() -> None:
    decision = evaluate_gate(_policy(), _evaluation([1, 2, 3], [1, 2, 3]))

    assert decision.status is GateStatus.PASS
    assert decision.rule_decisions[0].status is GateStatus.PASS


def test_gate_warns_when_ci_crosses_noninferiority_margin() -> None:
    # Point estimate (-0.0667) is within the -0.1 margin, but bootstrap uncertainty
    # extends below it; a point-estimate-only implementation would incorrectly pass.
    decision = evaluate_gate(_policy(), _evaluation([1, 1, 1], [0.8, 1, 1]))

    assert decision.rule_decisions[0].effect == pytest.approx(-0.2 / 3)
    assert decision.rule_decisions[0].confidence_low < -0.1  # type: ignore[operator]
    assert decision.rule_decisions[0].confidence_high >= -0.1  # type: ignore[operator]
    assert decision.status is GateStatus.WARN


def test_gate_blocks_clear_violation_and_supports_lower_is_better() -> None:
    higher_decision = evaluate_gate(_policy(), _evaluation([1, 1, 1], [0.7, 0.7, 0.7]))
    lower_decision = evaluate_gate(
        _policy(direction=MetricDirection.LOWER_IS_BETTER),
        _evaluation([1, 1, 1], [1.3, 1.3, 1.3]),
    )

    assert higher_decision.status is GateStatus.BLOCK
    assert lower_decision.status is GateStatus.BLOCK


def test_insufficient_evidence_never_passes_and_policy_can_error() -> None:
    evidence = _evaluation([1, 1, 1], [2, 2, 2])

    warn = evaluate_gate(_policy(min_pairs=4), evidence)
    error = evaluate_gate(
        _policy(min_pairs=4, insufficient=GateStatus.ERROR),
        evidence,
    )

    assert warn.status is GateStatus.WARN
    assert error.status is GateStatus.ERROR


def test_holm_bonferroni_uses_one_family_and_adjusted_intervals() -> None:
    policy = GatePolicy(
        policy_id="two-metric-family",
        rules=(
            GateRule(rule_id="quality", metric="quality", margin=0.1),
            GateRule(rule_id="safety", metric="safety", margin=0.1),
        ),
        familywise_alpha=0.05,
    )
    evidence = GateEvaluation(
        evidence=tuple(
            MetricEvidence(
                metric=metric,
                estimate=paired_bootstrap(
                    [1.0] * 20,
                    [1.0] * 20,
                    confidence_level=0.95,
                    additional_confidence_levels=(0.975,),
                    threshold=-0.1,
                    resamples=200,
                ),
            )
            for metric in ("quality", "safety")
        )
    )

    decision = evaluate_gate(policy, evidence)

    assert decision.status is GateStatus.PASS
    assert decision.family_size == 2
    assert decision.familywise_alpha == 0.05
    assert {item.confidence_level for item in decision.rule_decisions} == {0.975, 0.95}
    assert all(item.adjusted_p_value == 0.0 for item in decision.rule_decisions)


def test_explicit_mde_requirement_returns_insufficient_power() -> None:
    policy = GatePolicy(
        policy_id="powered-slice",
        rules=(
            GateRule(
                rule_id="rare-slice",
                metric="quality",
                margin=0.05,
                max_mde=0.05,
            ),
        ),
        insufficient_evidence_status=GateStatus.WARN,
    )
    evidence = _evaluation([0.0, 1.0, 0.0, 1.0], [1.0, 0.0, 1.0, 0.0])

    decision = evaluate_gate(policy, evidence)

    rule = decision.rule_decisions[0]
    assert decision.status is GateStatus.INSUFFICIENT_POWER
    assert rule.minimum_detectable_effect is not None
    assert rule.minimum_detectable_effect > 0.05
    assert "MDE" in rule.reason


def test_missing_evidence_is_error() -> None:
    decision = evaluate_gate(_policy(), GateEvaluation())

    assert decision.status is GateStatus.ERROR
    assert "missing" in decision.rule_decisions[0].reason


def test_any_critical_failure_directly_blocks() -> None:
    evaluation = _evaluation([1, 1, 1], [1, 1, 1]).model_copy(
        update={"critical_failures": ("safety/case-17",)}
    )
    decision = evaluate_gate(_policy(), evaluation)

    assert decision.rule_decisions[0].status is GateStatus.PASS
    assert decision.status is GateStatus.BLOCK
    assert decision.critical_failures == ("safety/case-17",)


def test_gate_contracts_forbid_unknown_fields_and_invalid_policy() -> None:
    with pytest.raises(ValidationError):
        GateRule(
            rule_id="r",
            metric="m",
            margin=0.0,
            surprise=True,  # type: ignore[call-arg]
        )
    with pytest.raises(ValidationError):
        GatePolicy(
            policy_id="duplicate",
            rules=(
                GateRule(rule_id="same", metric="one", margin=0.0),
                GateRule(rule_id="same", metric="two", margin=0.0),
            ),
        )


@pytest.mark.parametrize(
    ("baseline", "candidate"),
    [([], []), ([1.0], []), ([float("nan")], [1.0])],
)
def test_paired_bootstrap_rejects_invalid_evidence(
    baseline: list[float], candidate: list[float]
) -> None:
    with pytest.raises(ValueError):
        paired_bootstrap(baseline, candidate)


def test_serialized_policy_and_evidence_reject_non_finite_numbers() -> None:
    with pytest.raises(ValidationError):
        GateRule(rule_id="infinite-margin", metric="accuracy", margin=float("inf"))
    with pytest.raises(ValidationError):
        PairedEstimate(
            n_pairs=1,
            baseline_mean=float("nan"),
            candidate_mean=1.0,
            effect=0.0,
            effect_size=0.0,
            confidence_interval=ConfidenceInterval(
                low=0.0,
                high=0.0,
                confidence_level=0.95,
            ),
            resamples=1,
            seed=0,
        )


def test_statistical_edge_contracts_and_single_pair_path() -> None:
    with pytest.raises(ValidationError, match="finite"):
        ConfidenceInterval(low=float("nan"), high=1, confidence_level=0.95)
    with pytest.raises(ValidationError, match="must not exceed"):
        ConfidenceInterval(low=2, high=1, confidence_level=0.95)
    flips = BinaryFlipMatrix(both_pass=1, baseline_only=2, candidate_only=3, both_fail=4)
    assert flips.n_pairs == 10
    assert paired_bootstrap([1], [2], resamples=1).effect_size is None
    for arguments in (
        {"confidence_level": 1.0},
        {"resamples": 0},
    ):
        with pytest.raises(ValueError):
            paired_bootstrap([1], [1], **arguments)  # type: ignore[arg-type]
    for baseline, candidate in (([True], []), ([], [])):
        with pytest.raises(ValueError):
            binary_paired_evidence(baseline, candidate)
