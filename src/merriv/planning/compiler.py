"""Compile human policy and metric declarations before expensive execution."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from merriv.core.identity import fingerprint
from merriv.core.models import EvalCase, PluginRecord, RuntimeProfile
from merriv.gate import GatePolicy
from merriv.metrics import PairedMetric
from merriv.planning.models import (
    MAX_PLANNED_METRICS,
    CompiledReleasePlan,
    PlannedMetric,
    RuleBinding,
)
from merriv.plugins.registry import MetricDeclaration, _validate_metric


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


def _validate_cases(cases: Sequence[EvalCase]) -> tuple[EvalCase, ...]:
    ordered = tuple(cases)
    if not ordered:
        raise PlanCompileError("release plan requires at least one evaluation case")
    case_ids = [case.case_id for case in ordered]
    if len(case_ids) != len(set(case_ids)):
        raise PlanCompileError("release plan case IDs must be unique")
    return ordered


def _validate_sampling(resamples: int, confidence_level: float) -> None:
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples < 1:
        raise PlanCompileError("release plan resamples must be a positive integer")
    if (
        isinstance(confidence_level, bool)
        or not isinstance(confidence_level, (int, float))
        or not math.isfinite(confidence_level)
        or not 0 < confidence_level < 1
    ):
        raise PlanCompileError("release plan confidence level must be between zero and one")


def _declare_metrics(metrics: Sequence[PairedMetric]) -> tuple[MetricDeclaration, ...]:
    declared = tuple(metrics)
    if not declared:
        raise PlanCompileError("release plan requires at least one metric")
    if len(declared) > MAX_PLAN_BASE_METRICS:
        raise PlanCompileError("release plan base-metric capacity exceeded")

    declarations: list[MetricDeclaration] = []
    metric_ids: set[str] = set()
    for metric in declared:
        try:
            declaration = _validate_metric(metric)
        except Exception:
            raise PlanCompileError("release plan contains an invalid metric declaration") from None
        if declaration.metric_id in metric_ids:
            raise PlanCompileError(
                f"metric id {declaration.metric_id!r} is declared more than once"
            )
        metric_ids.add(declaration.metric_id)
        declarations.append(declaration)
    return tuple(declarations)


def _slice_values(
    cases: Sequence[EvalCase], slice_keys: Sequence[str]
) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    normalized_keys = tuple(
        _safe_slice_component(key, label="slice key", max_length=64) for key in slice_keys
    )
    if len(normalized_keys) != len(set(normalized_keys)):
        raise PlanCompileError("slice keys must be unique")
    if len(normalized_keys) > MAX_PLAN_SLICE_KEYS:
        raise PlanCompileError("release plan slice-key capacity exceeded")

    values_by_key: dict[str, tuple[str, ...]] = {}
    for key in normalized_keys:
        values = {
            _safe_slice_component(
                case.slices[key],
                label=f"slice value for {key!r}",
                max_length=128,
            )
            for case in cases
            if key in case.slices
        }
        if len(values) > MAX_PLAN_SLICE_VALUES_PER_KEY:
            raise PlanCompileError(f"slice key {key!r} exceeds its value capacity")
        if not values:
            raise PlanCompileError(f"slice key {key!r} is absent from every evaluation case")
        values_by_key[key] = tuple(sorted(values))
    return normalized_keys, values_by_key


def _validate_plugin_provenance(
    metric_ids: set[str], metric_plugins: Mapping[str, PluginRecord] | None
) -> dict[str, PluginRecord]:
    plugins = dict(metric_plugins or {})
    if set(plugins) - metric_ids:
        raise PlanCompileError("plugin provenance references an undeclared metric")
    for plugin in plugins.values():
        if plugin.kind not in {"metric", "unknown"}:
            raise PlanCompileError("metric provenance has an incompatible plugin kind")
        _safe_plugin_component(
            plugin.name,
            label="plugin name",
            max_length=128,
            punctuation="._-",
        )
        _safe_plugin_component(
            plugin.version,
            label="plugin version",
            max_length=64,
            punctuation=".+_-",
        )
        _safe_plugin_component(
            plugin.api_version,
            label="plugin API version",
            max_length=64,
            punctuation=".+_-",
        )
        for capability in plugin.capabilities:
            _safe_plugin_component(
                capability,
                label="plugin capability",
                max_length=128,
                punctuation="._:-",
            )
    return plugins


def _plan_metrics(
    declarations: Sequence[MetricDeclaration],
    values_by_key: Mapping[str, Sequence[str]],
    plugins: Mapping[str, PluginRecord],
) -> tuple[PlannedMetric, ...]:
    planned: list[PlannedMetric] = []
    for declaration in declarations:
        plugin = plugins.get(declaration.metric_id)
        plugin_name = plugin.name if plugin else None
        plugin_version = plugin.version if plugin else None
        planned.append(
            PlannedMetric(
                metric_id=declaration.metric_id,
                base_metric_id=declaration.metric_id,
                scope="overall",
                direction=declaration.direction,
                unit=declaration.unit,
                binary=declaration.binary,
                plugin_name=plugin_name,
                plugin_version=plugin_version,
            )
        )
        for slice_key, values in values_by_key.items():
            for value in values:
                if len(planned) >= MAX_PLANNED_METRICS:
                    raise PlanCompileError("release plan metric capacity exceeded")
                planned.append(
                    PlannedMetric(
                        metric_id=f"{declaration.metric_id}@{slice_key}={value}",
                        base_metric_id=declaration.metric_id,
                        scope=f"slice:{slice_key}={value}",
                        direction=declaration.direction,
                        unit=declaration.unit,
                        binary=declaration.binary,
                        plugin_name=plugin_name,
                        plugin_version=plugin_version,
                    )
                )
    if len(planned) > MAX_PLANNED_METRICS:
        raise PlanCompileError("release plan metric capacity exceeded")
    return tuple(planned)


def _bind_rules(policy: GatePolicy, planned: Sequence[PlannedMetric]) -> tuple[RuleBinding, ...]:
    planned_by_id = {metric.metric_id: metric for metric in planned}
    bindings: list[RuleBinding] = []
    for rule in policy.rules:
        metric = planned_by_id.get(rule.metric)
        if metric is None:
            raise PlanCompileError(
                f"policy rule {rule.rule_id!r} requires unavailable metric {rule.metric!r}"
            )
        if metric.direction is not rule.direction:
            raise PlanCompileError(
                f"policy direction for {rule.metric!r} does not match the metric declaration"
            )
        bindings.append(
            RuleBinding(
                rule_id=rule.rule_id,
                metric_id=rule.metric,
                base_metric_id=metric.base_metric_id,
            )
        )
    return tuple(bindings)


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
    ordered_cases = _validate_cases(cases)
    declarations = _declare_metrics(metrics)
    _validate_sampling(resamples, confidence_level)
    profile = runtime_profile or RuntimeProfile()
    _safe_plan_identifier(policy.policy_id, label="policy id")
    for rule in policy.rules:
        _safe_plan_identifier(rule.rule_id, label="rule id")
        _safe_plan_identifier(rule.metric, label="rule metric id")
    normalized_slice_keys, values_by_key = _slice_values(ordered_cases, slice_keys)
    plugins_by_metric = _validate_plugin_provenance(
        {declaration.metric_id for declaration in declarations}, metric_plugins
    )
    planned = _plan_metrics(declarations, values_by_key, plugins_by_metric)
    bindings = _bind_rules(policy, planned)

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
        "metrics": planned,
        "bindings": bindings,
        "plugins": plugins,
    }
    plan_digest = fingerprint(payload, namespace="release-plan")
    return CompiledReleasePlan(
        id=f"mcr:sha256:{plan_digest}",
        policy_id=policy.policy_id,
        policy_fingerprint=policy_fingerprint,
        suite_fingerprint=suite_fingerprint,
        runtime_profile_fingerprint=runtime_profile_fingerprint,
        seed=profile.seed,
        resamples=resamples,
        confidence_level=confidence_level,
        slice_keys=normalized_slice_keys,
        metrics=planned,
        bindings=bindings,
        plugins=plugins,
    )
