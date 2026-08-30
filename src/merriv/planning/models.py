"""Content-addressed release plan contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from merriv.core.models import ContentId, Contract, Digest, PluginRecord
from merriv.gate import MetricDirection

MAX_PLANNED_METRICS = 10_000

SafePlanIdentifier = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@=/-]{0,383}$"),
]
SafeBaseMetricId = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"),
]
SafeSliceKey = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"),
]
SafeMetricUnit = Annotated[
    str,
    StringConstraints(pattern=r"^[!-~][ -~]{0,63}$"),
]


class PlannedMetric(Contract):
    metric_id: SafePlanIdentifier
    base_metric_id: SafeBaseMetricId
    scope: SafePlanIdentifier
    direction: MetricDirection
    unit: SafeMetricUnit
    binary: bool
    plugin_name: SafeBaseMetricId | None = None
    plugin_version: Annotated[
        str | None, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9.+_-]{0,63}$")
    ] = None


class RuleBinding(Contract):
    rule_id: SafePlanIdentifier
    metric_id: SafePlanIdentifier
    base_metric_id: SafeBaseMetricId


class CompiledReleasePlan(Contract):
    """Preflight proof that a policy can be evaluated by the declared metrics."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    id: ContentId
    policy_id: SafePlanIdentifier
    policy_fingerprint: Digest
    suite_fingerprint: Digest
    runtime_profile_fingerprint: Digest
    seed: int
    resamples: int = Field(ge=1)
    confidence_level: float = Field(gt=0, lt=1)
    slice_keys: tuple[SafeSliceKey, ...] = Field(default=(), max_length=32)
    metrics: tuple[PlannedMetric, ...] = Field(min_length=1, max_length=MAX_PLANNED_METRICS)
    bindings: tuple[RuleBinding, ...] = Field(min_length=1, max_length=10_000)
    plugins: tuple[PluginRecord, ...] = Field(default=(), max_length=128)
