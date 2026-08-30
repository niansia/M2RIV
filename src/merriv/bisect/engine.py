"""Fail-closed regression bisection for ordered model checkpoints."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from merriv.gate import GateStatus


class BisectStatus(StrEnum):
    """The only statuses an ordered checkpoint evaluation may return."""

    PASS = "pass"  # nosec B105  # noqa: S105 - release status, not a credential
    BLOCK = "block"
    WARN = "warn"
    ERROR = "error"


class BisectMode(StrEnum):
    """Search strategy and its monotonicity assumptions."""

    MONOTONIC = "monotonic"
    SPARSE_AUDIT = "sparse_audit"
    LINEAR_AUDIT = "linear_audit"


class BisectOutcome(StrEnum):
    """High-level outcome of a bisect run."""

    ALL_PASS = "all_pass"  # nosec B105  # noqa: S105 - outcome, not a credential
    FIRST_FAILING = "first_failing"
    REGRESSION_BOUNDED = "regression_bounded"
    NO_FAILURE_OBSERVED = "no_failure_observed"
    NON_MONOTONIC = "non_monotonic"
    INCONCLUSIVE = "inconclusive"


class BisectConfidence(StrEnum):
    """What justifies the reported result.

    ``ASSUMED_MONOTONIC`` is conditional on the caller's monotonicity promise.
    ``SPARSE_AUDIT`` only describes sampled checkpoints. ``EXHAUSTIVE_AUDIT``
    means every checkpoint was evaluated. ``NONE`` never supports an onset.
    """

    ASSUMED_MONOTONIC = "assumed_monotonic"
    SPARSE_AUDIT = "sparse_audit"
    EXHAUSTIVE_AUDIT = "exhaustive_audit"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class EvaluationRecord:
    """One request to evaluate an index, including cache provenance."""

    index: int
    status: BisectStatus
    cache_hit: bool
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class IndexInterval:
    """A passing lower bound and blocking upper bound around an onset.

    ``lower_pass_index`` is ``None`` when index zero already blocks.
    """

    lower_pass_index: int | None
    upper_block_index: int


@dataclass(frozen=True, slots=True)
class NonMonotonicInterval:
    """Observed BLOCK followed by a later PASS, disproving monotonicity."""

    block_index: int
    later_pass_index: int


@dataclass(frozen=True, slots=True)
class BisectResult:
    """Auditable result of ordered regression localization."""

    outcome: BisectOutcome
    checkpoint_count: int
    first_failing_index: int | None
    confirmed_interval: IndexInterval | None
    non_monotonic_intervals: tuple[NonMonotonicInterval, ...]
    evaluations: tuple[EvaluationRecord, ...]
    requests: tuple[EvaluationRecord, ...]
    cache_hits: int
    confidence: BisectConfidence
    reason: str

    @property
    def evaluated_indices(self) -> tuple[int, ...]:
        """Indices actually sent to the callback, in evaluation order."""

        return tuple(record.index for record in self.evaluations)

    @property
    def evaluated_statuses(self) -> tuple[BisectStatus, ...]:
        """Callback statuses corresponding to :attr:`evaluated_indices`."""

        return tuple(record.status for record in self.evaluations)


StatusLike = BisectStatus | GateStatus | str
EvaluateCallback = Callable[[int], StatusLike]


def _normalize_status(value: StatusLike) -> BisectStatus:
    if isinstance(value, BisectStatus):
        return value
    if value is GateStatus.INSUFFICIENT_POWER:
        return BisectStatus.WARN
    raw_value = value.value if isinstance(value, GateStatus) else value
    try:
        return BisectStatus(raw_value.lower())
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"unsupported bisect status: {value!r}") from exc


class _CachedEvaluator:
    def __init__(self, checkpoint_count: int, callback: EvaluateCallback) -> None:
        self._checkpoint_count = checkpoint_count
        self._callback = callback
        self._cache: dict[int, EvaluationRecord] = {}
        self.requests: list[EvaluationRecord] = []

    def get(self, index: int) -> BisectStatus:
        if not 0 <= index < self._checkpoint_count:
            raise IndexError(f"checkpoint index out of range: {index}")
        cached = self._cache.get(index)
        if cached is not None:
            self.requests.append(
                EvaluationRecord(
                    index=index,
                    status=cached.status,
                    cache_hit=True,
                    detail=cached.detail,
                )
            )
            return cached.status

        detail: str | None = None
        try:
            status = _normalize_status(self._callback(index))
        except Exception as exc:  # callback failures are evidence failures, not PASS
            status = BisectStatus.ERROR
            # Exception messages commonly contain request URLs, credentials, or
            # model inputs. Evidence may be retained indefinitely, so record only
            # the exception class and never persist the untrusted message.
            detail = f"callback raised {type(exc).__name__}"
        record = EvaluationRecord(index=index, status=status, cache_hit=False, detail=detail)
        self._cache[index] = record
        self.requests.append(record)
        return status

    @property
    def evaluations(self) -> tuple[EvaluationRecord, ...]:
        return tuple(record for record in self.requests if not record.cache_hit)


def _result(
    evaluator: _CachedEvaluator,
    *,
    checkpoint_count: int,
    outcome: BisectOutcome,
    first_failing_index: int | None = None,
    confirmed_interval: IndexInterval | None = None,
    non_monotonic_intervals: tuple[NonMonotonicInterval, ...] = (),
    confidence: BisectConfidence,
    reason: str,
) -> BisectResult:
    requests = tuple(evaluator.requests)
    return BisectResult(
        outcome=outcome,
        checkpoint_count=checkpoint_count,
        first_failing_index=first_failing_index,
        confirmed_interval=confirmed_interval,
        non_monotonic_intervals=non_monotonic_intervals,
        evaluations=evaluator.evaluations,
        requests=requests,
        cache_hits=sum(record.cache_hit for record in requests),
        confidence=confidence,
        reason=reason,
    )


def _is_uncertain(status: BisectStatus) -> bool:
    return status in {BisectStatus.WARN, BisectStatus.ERROR}


def _monotonic_search(checkpoint_count: int, evaluator: _CachedEvaluator) -> BisectResult:
    first = evaluator.get(0)
    last = evaluator.get(checkpoint_count - 1)
    if _is_uncertain(first) or _is_uncertain(last):
        return _result(
            evaluator,
            checkpoint_count=checkpoint_count,
            outcome=BisectOutcome.INCONCLUSIVE,
            confidence=BisectConfidence.NONE,
            reason="an endpoint returned WARN or ERROR; no onset can be claimed",
        )

    if first is BisectStatus.BLOCK:
        if last is BisectStatus.PASS:
            return _result(
                evaluator,
                checkpoint_count=checkpoint_count,
                outcome=BisectOutcome.NON_MONOTONIC,
                non_monotonic_intervals=(NonMonotonicInterval(0, checkpoint_count - 1),),
                confidence=BisectConfidence.NONE,
                reason="the first checkpoint blocks but the last passes",
            )
        return _result(
            evaluator,
            checkpoint_count=checkpoint_count,
            outcome=BisectOutcome.FIRST_FAILING,
            first_failing_index=0,
            confirmed_interval=IndexInterval(None, 0),
            confidence=BisectConfidence.ASSUMED_MONOTONIC,
            reason="index zero blocks under the monotonicity assumption",
        )

    if last is BisectStatus.PASS:
        return _result(
            evaluator,
            checkpoint_count=checkpoint_count,
            outcome=BisectOutcome.ALL_PASS,
            confidence=BisectConfidence.ASSUMED_MONOTONIC,
            reason="both endpoints pass under the monotonicity assumption",
        )

    lower_pass = 0
    upper_block = checkpoint_count - 1
    while upper_block - lower_pass > 1:
        midpoint = (lower_pass + upper_block) // 2
        status = evaluator.get(midpoint)
        if _is_uncertain(status):
            return _result(
                evaluator,
                checkpoint_count=checkpoint_count,
                outcome=BisectOutcome.INCONCLUSIVE,
                confirmed_interval=IndexInterval(lower_pass, upper_block),
                confidence=BisectConfidence.NONE,
                reason=f"checkpoint {midpoint} returned {status.value}; search is inconclusive",
            )
        if status is BisectStatus.PASS:
            lower_pass = midpoint
        else:
            upper_block = midpoint

    return _result(
        evaluator,
        checkpoint_count=checkpoint_count,
        outcome=BisectOutcome.FIRST_FAILING,
        first_failing_index=upper_block,
        confirmed_interval=IndexInterval(lower_pass, upper_block),
        confidence=BisectConfidence.ASSUMED_MONOTONIC,
        reason="adjacent PASS/BLOCK boundary found by monotonic binary search",
    )


def _sparse_indices(checkpoint_count: int, sparse_points: int) -> tuple[int, ...]:
    point_count = min(checkpoint_count, sparse_points)
    if point_count == 1:
        return (0,)
    # Integer arithmetic avoids platform-sensitive float rounding.
    return tuple(
        sorted(
            {point * (checkpoint_count - 1) // (point_count - 1) for point in range(point_count)}
        )
    )


def _audit(
    checkpoint_count: int,
    evaluator: _CachedEvaluator,
    *,
    mode: BisectMode,
    sparse_points: int,
) -> BisectResult:
    # Endpoint checks are intentionally repeated by the audit schedule. The
    # records prove the callback cache was used instead of rerunning evaluation.
    evaluator.get(0)
    evaluator.get(checkpoint_count - 1)
    indices = (
        tuple(range(checkpoint_count))
        if mode is BisectMode.LINEAR_AUDIT
        else _sparse_indices(checkpoint_count, sparse_points)
    )
    for index in indices:
        evaluator.get(index)

    ordered = sorted(evaluator.evaluations, key=lambda record: record.index)
    decisive = [record for record in ordered if not _is_uncertain(record.status)]
    reversals: list[NonMonotonicInterval] = []
    previous: EvaluationRecord | None = None
    for record in decisive:
        if (
            previous is not None
            and previous.status is BisectStatus.BLOCK
            and record.status is BisectStatus.PASS
        ):
            reversals.append(NonMonotonicInterval(previous.index, record.index))
        previous = record

    confidence = (
        BisectConfidence.EXHAUSTIVE_AUDIT
        if mode is BisectMode.LINEAR_AUDIT
        else BisectConfidence.SPARSE_AUDIT
    )
    uncertain = [record for record in ordered if _is_uncertain(record.status)]
    if uncertain:
        indices_text = ", ".join(str(record.index) for record in uncertain)
        return _result(
            evaluator,
            checkpoint_count=checkpoint_count,
            outcome=BisectOutcome.INCONCLUSIVE,
            confidence=BisectConfidence.NONE,
            reason=f"WARN or ERROR at checkpoint(s) {indices_text}; no onset can be claimed",
        )

    if reversals:
        return _result(
            evaluator,
            checkpoint_count=checkpoint_count,
            outcome=BisectOutcome.NON_MONOTONIC,
            non_monotonic_intervals=tuple(reversals),
            confidence=confidence,
            reason="observed BLOCK-to-PASS reversal(s); a single onset would be misleading",
        )

    first_block = next(
        (record.index for record in ordered if record.status is BisectStatus.BLOCK), None
    )
    if first_block is None:
        exhaustive = mode is BisectMode.LINEAR_AUDIT
        return _result(
            evaluator,
            checkpoint_count=checkpoint_count,
            outcome=(BisectOutcome.ALL_PASS if exhaustive else BisectOutcome.NO_FAILURE_OBSERVED),
            confidence=confidence,
            reason=(
                "all checkpoints pass"
                if exhaustive
                else "sampled checkpoints pass; unsampled behavior remains unknown"
            ),
        )

    lower_pass = next(
        (
            record.index
            for record in reversed(ordered)
            if record.index < first_block and record.status is BisectStatus.PASS
        ),
        None,
    )
    exact = mode is BisectMode.LINEAR_AUDIT or first_block == 0
    return _result(
        evaluator,
        checkpoint_count=checkpoint_count,
        outcome=(BisectOutcome.FIRST_FAILING if exact else BisectOutcome.REGRESSION_BOUNDED),
        first_failing_index=first_block if exact else None,
        confirmed_interval=IndexInterval(lower_pass, first_block),
        confidence=confidence,
        reason=(
            "first failing checkpoint found by exhaustive audit"
            if mode is BisectMode.LINEAR_AUDIT
            else "regression bounded by sparse audit; exact onset remains unknown"
        ),
    )


def bisect_regression(
    checkpoint_count: int,
    evaluate: EvaluateCallback,
    *,
    mode: BisectMode | str = BisectMode.MONOTONIC,
    sparse_points: int = 7,
) -> BisectResult:
    """Locate a regression in an ordered checkpoint sequence.

    The callback receives an integer index and may return :class:`BisectStatus`,
    :class:`~merriv.gate.GateStatus`, or a case-insensitive string status. Callback
    exceptions and unsupported values are captured as ``ERROR`` so an evaluation
    failure can never be silently treated as a passing checkpoint.

    ``MONOTONIC`` performs an O(log n) binary search after checking endpoints.
    Use an audit mode when monotonicity is unknown. Sparse audit provides sampled
    evidence only; linear audit evaluates every checkpoint and can exhaustively
    identify BLOCK-to-PASS reversals.
    """

    if (
        isinstance(checkpoint_count, bool)
        or not isinstance(checkpoint_count, int)
        or checkpoint_count < 1
    ):
        raise ValueError("checkpoint_count must be a positive integer")
    if isinstance(sparse_points, bool) or not isinstance(sparse_points, int) or sparse_points < 2:
        raise ValueError("sparse_points must be at least 2")
    try:
        strategy = BisectMode(mode)
    except ValueError as exc:
        raise ValueError(f"unsupported bisect mode: {mode!r}") from exc
    evaluator = _CachedEvaluator(checkpoint_count, evaluate)
    if strategy is BisectMode.MONOTONIC:
        return _monotonic_search(checkpoint_count, evaluator)
    if strategy in {BisectMode.SPARSE_AUDIT, BisectMode.LINEAR_AUDIT}:
        return _audit(
            checkpoint_count,
            evaluator,
            mode=strategy,
            sparse_points=sparse_points,
        )
    raise AssertionError("all BisectMode values must be handled")
