from __future__ import annotations

import random

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
    HypothesisTestEvidence,
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


def test_binary_zero_margin_uses_exact_mcnemar_for_holm_evidence() -> None:
    evidence = binary_paired_evidence(
        [True] * 12 + [False] * 4,
        [False] * 12 + [True] * 4,
        threshold=0.0,
        resamples=200,
    )

    hypothesis = evidence.estimate.hypothesis_test
    assert hypothesis is not None
    assert hypothesis.method == "exact-mcnemar"
    assert hypothesis.p_value == evidence.mcnemar_exact_p_value
    assert hypothesis.null_value == 0.0


def test_binary_nonzero_margin_matches_tango_score_reference_vector() -> None:
    evidence = binary_paired_evidence(
        [True] * 2 + [False] * 12 + [True] * 18 + [False] * 18,
        [False] * 2 + [True] * 12 + [True] * 18 + [False] * 18,
        threshold=-0.1,
        resamples=200,
    )

    hypothesis = evidence.estimate.hypothesis_test
    assert hypothesis is not None
    assert hypothesis.method == "tango-score-matched-proportions"
    assert hypothesis.null_value == -0.1
    assert hypothesis.p_value == pytest.approx(0.0002218466806632116)
    assert evidence.estimate.method == "tango-score-matched-proportions"
    assert evidence.estimate.confidence_interval.low == pytest.approx(0.0611124, abs=1e-7)
    assert evidence.estimate.confidence_interval.high == pytest.approx(0.3447087, abs=1e-7)


def test_tango_score_profile_is_symmetric_when_pair_orientation_is_reversed() -> None:
    evidence = binary_paired_evidence(
        [False] * 2 + [True] * 12 + [True] * 18 + [False] * 18,
        [True] * 2 + [False] * 12 + [True] * 18 + [False] * 18,
        threshold=0.1,
        resamples=200,
    )

    hypothesis = evidence.estimate.hypothesis_test
    assert hypothesis is not None
    assert hypothesis.p_value == pytest.approx(0.0002218466806632116)
    assert evidence.estimate.confidence_interval.low == pytest.approx(-0.3447087, abs=1e-7)
    assert evidence.estimate.confidence_interval.high == pytest.approx(-0.0611124, abs=1e-7)


@pytest.mark.parametrize(
    ("baseline_only", "candidate_only", "n_pairs", "threshold"),
    [(1, 1, 20, -0.05), (2, 12, 50, -0.1), (12, 2, 50, 0.1), (0, 5, 20, 0.05)],
)
def test_tango_score_interval_is_the_dual_of_its_two_sided_test(
    baseline_only: int,
    candidate_only: int,
    n_pairs: int,
    threshold: float,
) -> None:
    concordant = n_pairs - baseline_only - candidate_only
    evidence = binary_paired_evidence(
        [True] * baseline_only + [False] * candidate_only + [True] * concordant,
        [False] * baseline_only + [True] * candidate_only + [True] * concordant,
        threshold=threshold,
        resamples=100,
    )

    hypothesis = evidence.estimate.hypothesis_test
    assert hypothesis is not None
    interval = evidence.estimate.confidence_interval
    assert (interval.low <= threshold <= interval.high) is (hypothesis.p_value >= 0.05)


def test_binary_margin_at_support_boundary_emits_no_formal_score_test() -> None:
    evidence = binary_paired_evidence(
        [True, False],
        [False, True],
        threshold=-1.0,
        resamples=20,
    )

    assert evidence.estimate.hypothesis_test is None
    assert evidence.estimate.method == "paired-percentile-bootstrap"


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


def _evaluation(
    baseline: list[float],
    candidate: list[float],
    *,
    threshold: float = -0.1,
) -> GateEvaluation:
    return GateEvaluation(
        evidence=(
            MetricEvidence(
                metric="quality",
                estimate=paired_bootstrap(
                    baseline,
                    candidate,
                    threshold=threshold,
                    resamples=1_000,
                    seed=5,
                ),
            ),
        )
    )


def test_gate_passes_only_when_full_interval_meets_margin() -> None:
    decision = evaluate_gate(
        _policy(),
        _evaluation([1, 2, 3, 4, 5, 6], [1, 2, 3, 4, 5, 6]),
    )

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
    higher_decision = evaluate_gate(
        _policy(),
        _evaluation([1] * 6, [0.7] * 6),
    )
    lower_decision = evaluate_gate(
        _policy(direction=MetricDirection.LOWER_IS_BETTER),
        _evaluation([1] * 6, [1.3] * 6, threshold=0.1),
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
    assert all(
        item.adjusted_p_value == pytest.approx(2 / 201)
        for item in decision.rule_decisions
    )


def test_explicit_mde_requirement_returns_insufficient_power() -> None:
    policy = GatePolicy(
        policy_id="powered-slice",
        rules=(
            GateRule(
                rule_id="rare-slice",
                metric="quality",
                margin=0.05,
                max_mde=0.05,
                planned_difference_stddev=1.0,
            ),
        ),
        insufficient_evidence_status=GateStatus.WARN,
    )
    evidence = _evaluation(
        [0.0, 1.0, 0.0, 1.0],
        [1.0, 0.0, 1.0, 0.0],
        threshold=-0.05,
    )

    decision = evaluate_gate(policy, evidence)

    rule = decision.rule_decisions[0]
    assert decision.status is GateStatus.INSUFFICIENT_POWER
    assert rule.minimum_detectable_effect is not None
    assert rule.minimum_detectable_effect > 0.05
    assert "MDE" in rule.reason


def _manual_holm_evaluation(
    p_values: dict[str, float],
    *,
    family_size: int | None = None,
    interval_low: float = -1.0,
    interval_high: float = 1.0,
) -> GateEvaluation:
    declared_family_size = family_size or len(p_values)
    required_levels = tuple(
        1.0 - 0.05 / denominator
        for denominator in range(declared_family_size, 0, -1)
    )
    primary = 0.95
    additional = tuple(
        ConfidenceInterval(
            low=interval_low,
            high=interval_high,
            confidence_level=level,
        )
        for level in required_levels
        if pytest.approx(level, abs=1e-12) != primary
    )
    return GateEvaluation(
        evidence=tuple(
            MetricEvidence(
                metric=rule_id,
                estimate=PairedEstimate(
                    n_pairs=20,
                    baseline_mean=0.0,
                    candidate_mean=0.0,
                    effect=0.0,
                    effect_size=0.0,
                    difference_stddev=1.0,
                    confidence_interval=ConfidenceInterval(
                        low=interval_low,
                        high=interval_high,
                        confidence_level=primary,
                    ),
                    additional_confidence_intervals=additional,
                    hypothesis_test=HypothesisTestEvidence(
                        null_value=0.0,
                        p_value=p_value,
                        method="paired-sign-randomization-exact",
                    ),
                    resamples=1,
                    seed=0,
                ),
            )
            for rule_id, p_value in p_values.items()
        )
    )


def _holm_policy(rule_ids: tuple[str, ...]) -> GatePolicy:
    return GatePolicy(
        policy_id="adversarial-holm",
        rules=tuple(
            GateRule(rule_id=rule_id, metric=rule_id, margin=0.0)
            for rule_id in rule_ids
        ),
    )


def test_holm_ties_use_stable_rule_id_order() -> None:
    rule_ids = ("charlie", "alpha", "bravo")
    decision = evaluate_gate(
        _holm_policy(rule_ids),
        _manual_holm_evaluation({rule_id: 0.01 for rule_id in rule_ids}),
    )

    by_id = {item.rule_id: item for item in decision.rule_decisions}
    assert by_id["alpha"].effective_alpha == pytest.approx(0.05 / 3)
    assert by_id["bravo"].effective_alpha == pytest.approx(0.05 / 2)
    assert by_id["charlie"].effective_alpha == pytest.approx(0.05)
    assert {item.adjusted_p_value for item in decision.rule_decisions} == {0.03}


def test_single_rule_holm_degenerates_to_the_unadjusted_path() -> None:
    decision = evaluate_gate(
        _holm_policy(("only",)),
        _manual_holm_evaluation(
            {"only": 0.04},
            interval_low=0.1,
            interval_high=0.2,
        ),
    )

    rule = decision.rule_decisions[0]
    assert decision.family_size == 1
    assert rule.status is GateStatus.PASS
    assert rule.raw_p_value == 0.04
    assert rule.adjusted_p_value == 0.04
    assert rule.effective_alpha == 0.05


@pytest.mark.parametrize(
    "metric_names",
    [("overall",), ("overall", "slice")],
    ids=["singleton", "family"],
)
def test_holm_consumes_tango_score_for_nonzero_binary_test(
    metric_names: tuple[str, ...],
) -> None:
    estimate = binary_paired_evidence(
        [True] * 20,
        [True] * 18 + [False] * 2,
        confidence_level=0.95,
        additional_confidence_levels=(0.975,),
        threshold=-0.02,
        resamples=200,
    ).estimate
    policy = GatePolicy(
        policy_id="tango-binary-ni",
        rules=tuple(
            GateRule(rule_id=metric, metric=metric, margin=0.02)
            for metric in metric_names
        ),
    )
    evaluation = GateEvaluation(
        evidence=tuple(
            MetricEvidence(metric=metric, estimate=estimate)
            for metric in metric_names
        )
    )

    decision = evaluate_gate(policy, evaluation)

    assert decision.status is GateStatus.WARN
    assert all(item.status is GateStatus.WARN for item in decision.rule_decisions)
    assert all(
        item.raw_p_value == pytest.approx(0.21040645309537137)
        for item in decision.rule_decisions
    )
    assert all("tango-score-matched-proportions" in item.reason for item in decision.rule_decisions)


def test_complete_declared_family_includes_missing_and_underpowered_rules() -> None:
    policy = GatePolicy(
        policy_id="declared-family",
        rules=(
            GateRule(rule_id="tested", metric="tested", margin=0.0),
            GateRule(rule_id="missing", metric="missing", margin=0.0),
            GateRule(
                rule_id="underpowered",
                metric="underpowered",
                margin=0.0,
                max_mde=0.01,
                planned_difference_stddev=1.0,
            ),
        ),
    )
    evaluation = _manual_holm_evaluation(
        {"tested": 0.01, "underpowered": 0.01},
        family_size=3,
    )

    decision = evaluate_gate(policy, evaluation)
    by_id = {item.rule_id: item for item in decision.rule_decisions}
    assert decision.family_size == 3
    assert by_id["tested"].adjusted_p_value == pytest.approx(0.03)
    assert by_id["tested"].effective_alpha == pytest.approx(0.05 / 3)
    assert by_id["missing"].status is GateStatus.ERROR
    assert by_id["underpowered"].status is GateStatus.INSUFFICIENT_POWER


def test_complete_family_can_be_entirely_insufficient_power() -> None:
    rule_ids = ("one", "two", "three")
    policy = GatePolicy(
        policy_id="all-underpowered",
        rules=tuple(
            GateRule(
                rule_id=rule_id,
                metric=rule_id,
                margin=0.0,
                max_mde=0.01,
                planned_difference_stddev=1.0,
            )
            for rule_id in rule_ids
        ),
    )

    decision = evaluate_gate(
        policy,
        _manual_holm_evaluation({rule_id: 0.01 for rule_id in rule_ids}),
    )

    assert decision.status is GateStatus.INSUFFICIENT_POWER
    assert all(
        item.status is GateStatus.INSUFFICIENT_POWER
        and item.adjusted_p_value is None
        and item.effective_alpha == pytest.approx(0.05 / 3)
        for item in decision.rule_decisions
    )


def test_holm_adjusted_p_values_are_monotone_in_rank() -> None:
    rng = random.Random(20260830)  # noqa: S311 - deterministic property cases
    for family_size in range(2, 9):
        for iteration in range(20):
            p_values = {
                f"rule-{index:02d}": rng.random()
                for index in range(family_size)
            }
            decision = evaluate_gate(
                _holm_policy(tuple(p_values)),
                _manual_holm_evaluation(p_values),
            )
            ranked = sorted(
                decision.rule_decisions,
                key=lambda item: (item.raw_p_value, item.rule_id),
            )
            adjusted = [item.adjusted_p_value for item in ranked]
            assert all(value is not None for value in adjusted), iteration
            checked = [float(value) for value in adjusted if value is not None]
            assert checked == sorted(checked), iteration
            assert all(
                adjusted_value >= raw.raw_p_value  # type: ignore[operator]
                for adjusted_value, raw in zip(checked, ranked, strict=True)
            ), iteration


def test_max_mde_requires_prospectively_declared_stddev() -> None:
    with pytest.raises(ValidationError, match="planned_difference_stddev"):
        GateRule(rule_id="post-hoc", metric="quality", margin=0.0, max_mde=0.1)


def test_planned_stddev_makes_mde_independent_of_observed_spread() -> None:
    policy = GatePolicy(
        policy_id="planned-power",
        rules=(
            GateRule(
                rule_id="quality",
                metric="quality",
                margin=0.0,
                planned_difference_stddev=0.2,
            ),
        ),
    )
    low_spread = evaluate_gate(
        policy,
        _evaluation([0.0] * 20, [0.0] * 20, threshold=0.0),
    )
    high_spread = evaluate_gate(
        policy,
        _evaluation(
            [0.0] * 20,
            [float(index % 2) for index in range(20)],
            threshold=0.0,
        ),
    )

    assert low_spread.rule_decisions[0].minimum_detectable_effect == pytest.approx(
        high_spread.rule_decisions[0].minimum_detectable_effect
    )


def test_missing_evidence_is_error() -> None:
    decision = evaluate_gate(_policy(), GateEvaluation())

    assert decision.status is GateStatus.ERROR
    assert "missing" in decision.rule_decisions[0].reason


def test_any_critical_failure_directly_blocks() -> None:
    evaluation = _evaluation([1] * 6, [1] * 6).model_copy(
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
