from __future__ import annotations

import math

from m2riv.bisect import (
    BisectConfidence,
    BisectMode,
    BisectOutcome,
    BisectStatus,
    IndexInterval,
    NonMonotonicInterval,
    bisect_regression,
)
from m2riv.gate import GateStatus


def test_monotonic_binary_search_finds_first_failure_sublinearly() -> None:
    calls: list[int] = []

    def evaluate(index: int) -> BisectStatus:
        calls.append(index)
        return BisectStatus.PASS if index < 3 else BisectStatus.BLOCK

    result = bisect_regression(12, evaluate)

    assert result.outcome is BisectOutcome.FIRST_FAILING
    assert result.first_failing_index == 3
    assert result.confirmed_interval == IndexInterval(2, 3)
    assert result.confidence is BisectConfidence.ASSUMED_MONOTONIC
    assert len(calls) < 12
    assert len(calls) <= 2 + 4  # endpoints plus ceil(log2(11))
    assert result.evaluated_indices == tuple(calls)


def test_binary_search_is_exact_for_every_boundary_and_size() -> None:
    for checkpoint_count in range(2, 65):
        for first_failing in range(checkpoint_count):
            calls = 0

            def evaluate(index: int, boundary: int = first_failing) -> BisectStatus:
                nonlocal calls
                calls += 1
                return BisectStatus.PASS if index < boundary else BisectStatus.BLOCK

            result = bisect_regression(checkpoint_count, evaluate)

            assert result.first_failing_index == first_failing
            assert calls <= 2 + math.ceil(math.log2(checkpoint_count - 1))


def test_monotonic_search_handles_all_pass_and_first_item_failure() -> None:
    all_pass = bisect_regression(8, lambda _index: BisectStatus.PASS)
    first_fails = bisect_regression(8, lambda _index: BisectStatus.BLOCK)

    assert all_pass.outcome is BisectOutcome.ALL_PASS
    assert all_pass.first_failing_index is None
    assert first_fails.outcome is BisectOutcome.FIRST_FAILING
    assert first_fails.first_failing_index == 0
    assert first_fails.confirmed_interval == IndexInterval(None, 0)


def test_endpoint_reversal_disproves_monotonicity_without_onset_confidence() -> None:
    result = bisect_regression(
        5,
        lambda index: BisectStatus.BLOCK if index == 0 else BisectStatus.PASS,
    )

    assert result.outcome is BisectOutcome.NON_MONOTONIC
    assert result.first_failing_index is None
    assert result.non_monotonic_intervals == (NonMonotonicInterval(0, 4),)
    assert result.confidence is BisectConfidence.NONE


def test_single_checkpoint_uses_cache_instead_of_rerunning_callback() -> None:
    call_count = 0

    def evaluate(_index: int) -> str:
        nonlocal call_count
        call_count += 1
        return "PASS"

    result = bisect_regression(1, evaluate)

    assert result.outcome is BisectOutcome.ALL_PASS
    assert call_count == 1
    assert result.cache_hits == 1
    assert [record.cache_hit for record in result.requests] == [False, True]


def test_warn_error_and_callback_exception_are_never_treated_as_pass() -> None:
    warning = bisect_regression(
        4,
        lambda index: GateStatus.WARN if index == 0 else GateStatus.PASS,
    )

    def broken(index: int) -> BisectStatus:
        if index == 3:
            raise RuntimeError("Authorization: Bearer super-secret-api-key")
        return BisectStatus.PASS

    error = bisect_regression(4, broken)

    assert warning.outcome is BisectOutcome.INCONCLUSIVE
    assert warning.confidence is BisectConfidence.NONE
    assert error.outcome is BisectOutcome.INCONCLUSIVE
    error_record = next(record for record in error.evaluations if record.index == 3)
    assert error_record.status is BisectStatus.ERROR
    assert error_record.detail == "callback raised RuntimeError"
    assert "super-secret-api-key" not in repr(error)

    invalid = bisect_regression(2, lambda _index: "maybe")
    assert invalid.outcome is BisectOutcome.INCONCLUSIVE
    assert invalid.evaluations[0].status is BisectStatus.ERROR


def test_uncertain_midpoint_preserves_only_a_bounded_interval() -> None:
    statuses = ["pass", "pass", "warn", "block", "block"]
    result = bisect_regression(5, lambda index: statuses[index])

    assert result.outcome is BisectOutcome.INCONCLUSIVE
    assert result.first_failing_index is None
    assert result.confirmed_interval == IndexInterval(0, 4)
    assert result.confidence is BisectConfidence.NONE


def test_linear_audit_reports_every_non_monotonic_interval() -> None:
    statuses = [
        BisectStatus.PASS,
        BisectStatus.BLOCK,
        BisectStatus.PASS,
        BisectStatus.BLOCK,
        BisectStatus.BLOCK,
        BisectStatus.PASS,
    ]
    result = bisect_regression(
        len(statuses),
        lambda index: statuses[index],
        mode=BisectMode.LINEAR_AUDIT,
    )

    assert result.outcome is BisectOutcome.NON_MONOTONIC
    assert result.first_failing_index is None
    assert result.confirmed_interval is None
    assert result.non_monotonic_intervals == (
        NonMonotonicInterval(1, 2),
        NonMonotonicInterval(4, 5),
    )
    assert result.confidence is BisectConfidence.EXHAUSTIVE_AUDIT
    assert set(result.evaluated_indices) == set(range(len(statuses)))
    assert result.cache_hits == 2


def test_sparse_audit_detects_sampled_reversal_without_claiming_onset() -> None:
    statuses = [
        BisectStatus.PASS,
        BisectStatus.PASS,
        BisectStatus.BLOCK,
        BisectStatus.BLOCK,
        BisectStatus.PASS,
        BisectStatus.PASS,
    ]
    result = bisect_regression(
        len(statuses),
        lambda index: statuses[index],
        mode=BisectMode.SPARSE_AUDIT,
        sparse_points=4,
    )

    assert result.outcome is BisectOutcome.NON_MONOTONIC
    assert result.first_failing_index is None
    assert result.non_monotonic_intervals == (NonMonotonicInterval(3, 5),)
    assert result.confidence is BisectConfidence.SPARSE_AUDIT


def test_sparse_audit_marks_its_first_failure_as_sampled_only() -> None:
    result = bisect_regression(
        10,
        lambda index: BisectStatus.PASS if index < 5 else BisectStatus.BLOCK,
        mode=BisectMode.SPARSE_AUDIT,
        sparse_points=4,
    )

    assert result.outcome is BisectOutcome.REGRESSION_BOUNDED
    assert result.first_failing_index is None
    assert result.confirmed_interval == IndexInterval(3, 6)
    assert result.confidence is BisectConfidence.SPARSE_AUDIT
    assert "exact onset remains unknown" in result.reason


def test_sparse_all_pass_does_not_claim_every_checkpoint_passes() -> None:
    result = bisect_regression(
        20,
        lambda _index: BisectStatus.PASS,
        mode=BisectMode.SPARSE_AUDIT,
        sparse_points=4,
    )

    assert result.outcome is BisectOutcome.NO_FAILURE_OBSERVED
    assert result.confidence is BisectConfidence.SPARSE_AUDIT
    assert "unsampled behavior remains unknown" in result.reason


def test_linear_audit_gives_exhaustive_exact_onset() -> None:
    result = bisect_regression(
        7,
        lambda index: "PASS" if index < 4 else "BLOCK",
        mode=BisectMode.LINEAR_AUDIT,
    )

    assert result.outcome is BisectOutcome.FIRST_FAILING
    assert result.first_failing_index == 4
    assert result.confirmed_interval == IndexInterval(3, 4)
    assert result.confidence is BisectConfidence.EXHAUSTIVE_AUDIT


def test_invalid_arguments_fail_before_evaluation() -> None:
    calls = 0

    def evaluate(_index: int) -> BisectStatus:
        nonlocal calls
        calls += 1
        return BisectStatus.PASS

    for invalid_count in (0, -1, True):
        try:
            bisect_regression(invalid_count, evaluate)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid checkpoint count should fail")
    try:
        bisect_regression(2, evaluate, sparse_points=1)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid sparse point count should fail")
    try:
        bisect_regression(2, evaluate, mode="guess")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid mode should fail")
    assert calls == 0


def test_string_audit_mode_is_normalized_before_dispatch() -> None:
    result = bisect_regression(
        4,
        lambda index: "PASS" if index < 2 else "BLOCK",
        mode="linear_audit",
    )

    assert result.first_failing_index == 2
    assert result.confidence is BisectConfidence.EXHAUSTIVE_AUDIT
