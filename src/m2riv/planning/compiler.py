"""Compile human policy and metric declarations before expensive execution."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from m2riv.core.identity import fingerprint
from m2riv.core.models import EvalCase, PluginRecord, RuntimeProfile
from m2riv.gate import GatePolicy
from m2riv.metrics import PairedMetric
from m2riv.planning.models import (
    MAX_PLANNED_METRICS,
    CompiledReleasePlan,
    PlannedMetric,
    RuleBinding,
)
from m2riv.plugins.registry import MetricDeclaration, _validate_metric


class PlanCompileError(ValueError):
    """A release policy cannot be satisfied by the declared suite and metrics."""


MAX_PLAN_SLICE_KEYS = 32
MAX_PLAN_SLICE_VALUES_PER_KEY = 1_000
MAX_PLAN_BASE_METRICS = 256


def _safe_slice_component(value: str, *, label: str, max_length: int) -> str:
    if (
        not value
        or len(value) > max_length
        or not value[0].isalnum()
        or any(
            not (character.isascii() and (character.isalnum() or character in "._:/-"))
            for character in value
        )
    ):
        raise PlanCompileError(f"{label} must be a safe bounded ASCII identifier")
    return value


def _safe_plan_identifier(value: str, *, label: str) -> str:
    if (
        not value
        or len(value) > 384
        or not value[0].isalnum()
        or any(
            not (character.isascii() and (character.isalnum() or character in "._:@=/-"))
            for character in value
        )
    ):
        raise PlanCompileError(f"{label} must be a safe bounded ASCII identifier")
    return value


def _safe_plugin_component(value: str, *, label: str, max_length: int, punctuation: str) -> str:
    if (
        not value
        or len(value) > max_length
        or not value[0].isalnum()
        or any(
            not (character.isascii() and (character.isalnum() or character in punctuation))
            for character in value
        )
    ):
        raise PlanCompileError(f"{label} must be a safe bounded ASCII identifier")
    return value


def _plugin_for_metric(
    metric_id: str,
    metric_plugins: Mapping[str, PluginRecord],
) -> PluginRecord | None:
    return metric_plugins.get(metric_id)


def compile_release_plan(
    *,
    policy: GatePolicy,
    cases: Sequence[EvalCase],
    metrics: Sequence[PairedMetric],
    slice_keys: Sequence[str] = (),
    metric_plugins: Mapping[str, PluginRecord] | None = None,
    runtime_profile: RuntimeProfile | None = None,
    resamples: int = 2_000,
    confidence_level: float = 0.95,
) -> CompiledReleasePlan:
    """Prove metric/slice/rule compatibility and emit immutable plan identity."""
    ordered_cases = tuple(cases)
    declared_metrics = tuple(metrics)
    if not ordered_cases:
        raise PlanCompileError("release plan requires at least one evaluation case")
    case_ids = [case.case_id for case in ordered_cases]
    if len(case_ids) != len(set(case_ids)):
        raise PlanCompileError("release plan case IDs must be unique")
    if not declared_metrics:
        raise PlanCompileError("release plan requires at least one metric")
    if len(declared_metrics) > MAX_PLAN_BASE_METRICS:
        raise PlanCompileError("release plan base-metric capacity exceeded")
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples < 1:
        raise PlanCompileError("release plan resamples must be a positive integer")
    if (
        isinstance(confidence_level, bool)
        or not isinstance(confidence_level, (int, float))
        or not math.isfinite(confidence_level)
        or not 0 < confidence_level < 1
    ):
        raise PlanCompileError("release plan confidence level must be between zero and one")
    profile = runtime_profile or RuntimeProfile()
    _safe_plan_identifier(policy.policy_id, label="policy id")
    for rule in policy.rules:
        _safe_plan_identifier(rule.rule_id, label="rule id")
        _safe_plan_identifier(rule.metric, label="rule metric id")

    metric_by_id: dict[str, PairedMetric] = {}
    metric_declarations: list[MetricDeclaration] = []
    for metric in declared_metrics:
        try:
            declaration = _validate_metric(metric)
        except Exception:
            raise PlanCompileError("release plan contains an invalid metric declaration") from None
        metric_id = declaration.metric_id
        if metric_id in metric_by_id:
            raise PlanCompileError(f"metric id {metric_id!r} is declared more than once")
        metric_by_id[metric_id] = metric
        metric_declarations.append(declaration)

    normalized_slice_keys = tuple(
        _safe_slice_component(key, label="slice key", max_length=64) for key in slice_keys
    )
    if len(normalized_slice_keys) != len(set(normalized_slice_keys)):
        raise PlanCompileError("slice keys must be unique")
    if len(normalized_slice_keys) > MAX_PLAN_SLICE_KEYS:
        raise PlanCompileError("release plan slice-key capacity exceeded")

    plugins_by_metric = dict(metric_plugins or {})
    unknown_plugin_metrics = set(plugins_by_metric) - set(metric_by_id)
    if unknown_plugin_metrics:
        raise PlanCompileError("plugin provenance references an undeclared metric")
    for declared_plugin in plugins_by_metric.values():
        if declared_plugin.kind not in {"metric", "unknown"}:
            raise PlanCompileError("metric provenance has an incompatible plugin kind")
        _safe_plugin_component(
            declared_plugin.name,
            label="plugin name",
            max_length=128,
            punctuation="._-",
        )
        _safe_plugin_component(
            declared_plugin.version,
            label="plugin version",
            max_length=64,
            punctuation=".+_-",
        )
        _safe_plugin_component(
            declared_plugin.api_version,
            label="plugin API version",
            max_length=64,
            punctuation=".+_-",
        )
        for capability in declared_plugin.capabilities:
            _safe_plugin_component(
                capability,
                label="plugin capability",
                max_length=128,
                punctuation="._:-",
            )

    planned: list[PlannedMetric] = []
    for declaration in metric_declarations:
        metric_id = declaration.metric_id
        metric_plugin = _plugin_for_metric(metric_id, plugins_by_metric)
        planned.append(
            PlannedMetric(
                metric_id=metric_id,
                base_metric_id=metric_id,
                scope="overall",
                direction=declaration.direction,
                unit=declaration.unit,
                binary=declaration.binary,
                plugin_name=metric_plugin.name if metric_plugin else None,
                plugin_version=metric_plugin.version if metric_plugin else None,
            )
        )
        if len(planned) > MAX_PLANNED_METRICS:
            raise PlanCompileError("release plan metric capacity exceeded")
        for slice_key in normalized_slice_keys:
            value_set: set[str] = set()
            for case in ordered_cases:
                if slice_key not in case.slices:
                    continue
                value_set.add(
                    _safe_slice_component(
                        case.slices[slice_key],
                        label=f"slice value for {slice_key!r}",
                        max_length=128,
                    )
                )
                if len(value_set) > MAX_PLAN_SLICE_VALUES_PER_KEY:
                    raise PlanCompileError(f"slice key {slice_key!r} exceeds its value capacity")
            if not value_set:
                raise PlanCompileError(
                    f"slice key {slice_key!r} is absent from every evaluation case"
                )
            values = sorted(value_set)
            for value in values:
                if len(planned) >= MAX_PLANNED_METRICS:
                    raise PlanCompileError("release plan metric capacity exceeded")
                planned.append(
                    PlannedMetric(
                        metric_id=f"{metric_id}@{slice_key}={value}",
                        base_metric_id=metric_id,
                        scope=f"slice:{slice_key}={value}",
                        direction=declaration.direction,
                        unit=declaration.unit,
                        binary=declaration.binary,
                        plugin_name=metric_plugin.name if metric_plugin else None,
                        plugin_version=metric_plugin.version if metric_plugin else None,
                    )
                )

    planned_by_id = {metric.metric_id: metric for metric in planned}
    bindings: list[RuleBinding] = []
    for rule in policy.rules:
        planned_metric = planned_by_id.get(rule.metric)
        if planned_metric is None:
            raise PlanCompileError(
                f"policy rule {rule.rule_id!r} requires unavailable metric {rule.metric!r}"
            )
        if planned_metric.direction is not rule.direction:
            raise PlanCompileError(
                f"policy direction for {rule.metric!r} does not match the metric declaration"
            )
        bindings.append(
            RuleBinding(
                rule_id=rule.rule_id,
                metric_id=rule.metric,
                base_metric_id=planned_metric.base_metric_id,
            )
        )

    unique_plugins = {
        fingerprint(plugin, namespace="plugin-record"): plugin
        for plugin in plugins_by_metric.values()
    }
    plugins = tuple(unique_plugins[key] for key in sorted(unique_plugins))
    policy_fingerprint = fingerprint(policy, namespace="gate-policy")
    suite_fingerprint = fingerprint(ordered_cases, namespace="eval-suite")
    runtime_profile_fingerprint = fingerprint(profile, namespace="runtime-profile")
    payload = {
        "schema_version": "1.0.0",
        "policy_id": policy.policy_id,
        "policy_fingerprint": policy_fingerprint,
        "suite_fingerprint": suite_fingerprint,
        "runtime_profile_fingerprint": runtime_profile_fingerprint,
        "seed": profile.seed,
        "resamples": resamples,
        "confidence_level": confidence_level,
        "slice_keys": normalized_slice_keys,
        "metrics": tuple(planned),
        "bindings": tuple(bindings),
        "plugins": plugins,
    }
    plan_digest = fingerprint(payload, namespace="release-plan")
    return CompiledReleasePlan(
        id=f"m2riv:sha256:{plan_digest}",
        policy_id=policy.policy_id,
        policy_fingerprint=policy_fingerprint,
        suite_fingerprint=suite_fingerprint,
        runtime_profile_fingerprint=runtime_profile_fingerprint,
        seed=profile.seed,
        resamples=resamples,
        confidence_level=confidence_level,
        slice_keys=normalized_slice_keys,
        metrics=tuple(planned),
        bindings=tuple(bindings),
        plugins=plugins,
    )
