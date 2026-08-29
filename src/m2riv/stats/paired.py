"""Dependency-free, deterministic statistics for paired model comparisons."""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StatisticalContract(BaseModel):
    """Strict, immutable statistical evidence suitable for serialization."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ConfidenceInterval(StatisticalContract):
    """A two-sided interval with explicit coverage."""

    low: float
    high: float
    confidence_level: Annotated[float, Field(gt=0.0, lt=1.0)]

    @model_validator(mode="after")
    def ordered_and_finite(self) -> ConfidenceInterval:
        if not math.isfinite(self.low) or not math.isfinite(self.high):
            raise ValueError("confidence interval bounds must be finite")
        if self.low > self.high:
            raise ValueError("confidence interval low must not exceed high")
        return self


class PairedEstimate(StatisticalContract):
    """Mean candidate-minus-baseline effect with paired bootstrap uncertainty."""

    n_pairs: Annotated[int, Field(ge=1)]
    baseline_mean: float
    candidate_mean: float
    effect: float
    effect_size: float | None
    confidence_interval: ConfidenceInterval
    method: Literal["paired-percentile-bootstrap"] = "paired-percentile-bootstrap"
    resamples: Annotated[int, Field(ge=1)]
    seed: int


class BinaryFlipMatrix(StatisticalContract):
    """Paired correctness transitions from baseline to candidate."""

    both_pass: Annotated[int, Field(ge=0)]
    baseline_only: Annotated[int, Field(ge=0)]
    candidate_only: Annotated[int, Field(ge=0)]
    both_fail: Annotated[int, Field(ge=0)]

    @property
    def n_pairs(self) -> int:
        return self.both_pass + self.baseline_only + self.candidate_only + self.both_fail

    @property
    def discordant_pairs(self) -> int:
        return self.baseline_only + self.candidate_only


class BinaryPairedEvidence(StatisticalContract):
    """Binary paired effect, transitions, and exact McNemar evidence."""

    estimate: PairedEstimate
    flips: BinaryFlipMatrix
    mcnemar_exact_p_value: Annotated[float, Field(ge=0.0, le=1.0)]


def _validate_numeric_pairs(
    baseline: Sequence[float], candidate: Sequence[float]
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    if len(baseline) != len(candidate):
        raise ValueError("baseline and candidate must contain the same number of pairs")
    if not baseline:
        raise ValueError("at least one paired observation is required")
    baseline_values = tuple(float(value) for value in baseline)
    candidate_values = tuple(float(value) for value in candidate)
    if not all(math.isfinite(value) for value in baseline_values + candidate_values):
        raise ValueError("paired observations must be finite")
    return baseline_values, candidate_values


def _quantile(sorted_values: Sequence[float], probability: float) -> float:
    """Return a linearly interpolated quantile (R/NumPy type 7)."""

    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def paired_bootstrap(
    baseline: Sequence[float],
    candidate: Sequence[float],
    *,
    confidence_level: float = 0.95,
    resamples: int = 10_000,
    seed: int = 0,
) -> PairedEstimate:
    """Estimate a paired mean effect and deterministic percentile-bootstrap CI.

    Pairing is preserved by resampling candidate-minus-baseline differences, not
    the two model samples independently. The effect sign is always candidate minus
    baseline. A local PRNG makes results repeatable and does not mutate global state.
    """

    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must be between zero and one")
    if resamples < 1:
        raise ValueError("resamples must be positive")
    baseline_values, candidate_values = _validate_numeric_pairs(baseline, candidate)
    differences = tuple(
        candidate_value - baseline_value
        for baseline_value, candidate_value in zip(baseline_values, candidate_values, strict=True)
    )
    n_pairs = len(differences)
    baseline_mean = math.fsum(baseline_values) / n_pairs
    candidate_mean = math.fsum(candidate_values) / n_pairs
    effect = math.fsum(differences) / n_pairs
    # Cohen's dz: the mean paired difference standardized by the sample
    # deviation of those differences. It is undefined for a single pair or a
    # non-zero constant difference, and exactly zero for identical pairs.
    effect_size: float | None
    if n_pairs < 2:
        effect_size = None
    else:
        squared_deviations = math.fsum((value - effect) ** 2 for value in differences)
        difference_stddev = math.sqrt(squared_deviations / (n_pairs - 1))
        if difference_stddev == 0.0:
            effect_size = 0.0 if effect == 0.0 else None
        else:
            effect_size = effect / difference_stddev

    # Reproducible bootstrap sampling, not a cryptographic decision.
    rng = random.Random(seed)  # nosec B311  # noqa: S311
    bootstrap_effects = [
        math.fsum(differences[rng.randrange(n_pairs)] for _ in range(n_pairs)) / n_pairs
        for _ in range(resamples)
    ]
    bootstrap_effects.sort()
    alpha = (1.0 - confidence_level) / 2.0
    interval = ConfidenceInterval(
        low=_quantile(bootstrap_effects, alpha),
        high=_quantile(bootstrap_effects, 1.0 - alpha),
        confidence_level=confidence_level,
    )
    return PairedEstimate(
        n_pairs=n_pairs,
        baseline_mean=baseline_mean,
        candidate_mean=candidate_mean,
        effect=effect,
        effect_size=effect_size,
        confidence_interval=interval,
        resamples=resamples,
        seed=seed,
    )


def _exact_mcnemar_p_value(baseline_only: int, candidate_only: int) -> float:
    discordant = baseline_only + candidate_only
    if discordant == 0:
        return 1.0
    smaller = min(baseline_only, candidate_only)
    # Sum integers exactly before division. Converting individual large binomial
    # coefficients to floats can overflow for ordinary large evaluation suites.
    lower_tail = sum(math.comb(discordant, k) for k in range(smaller + 1)) / (1 << discordant)
    return float(min(1.0, 2.0 * lower_tail))


def binary_paired_evidence(
    baseline: Sequence[bool],
    candidate: Sequence[bool],
    *,
    confidence_level: float = 0.95,
    resamples: int = 10_000,
    seed: int = 0,
) -> BinaryPairedEvidence:
    """Summarize paired pass/fail changes, including an exact McNemar p-value."""

    if len(baseline) != len(candidate):
        raise ValueError("baseline and candidate must contain the same number of pairs")
    if not baseline:
        raise ValueError("at least one paired observation is required")
    flips = BinaryFlipMatrix(
        both_pass=sum(left and right for left, right in zip(baseline, candidate, strict=True)),
        baseline_only=sum(
            left and not right for left, right in zip(baseline, candidate, strict=True)
        ),
        candidate_only=sum(
            not left and right for left, right in zip(baseline, candidate, strict=True)
        ),
        both_fail=sum(
            not left and not right for left, right in zip(baseline, candidate, strict=True)
        ),
    )
    estimate = paired_bootstrap(
        [float(value) for value in baseline],
        [float(value) for value in candidate],
        confidence_level=confidence_level,
        resamples=resamples,
        seed=seed,
    )
    return BinaryPairedEvidence(
        estimate=estimate,
        flips=flips,
        mcnemar_exact_p_value=_exact_mcnemar_p_value(flips.baseline_only, flips.candidate_only),
    )
