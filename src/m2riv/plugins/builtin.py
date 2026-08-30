"""Canonical registry containing dependency-free Merriv metrics."""

from __future__ import annotations

from m2riv import __version__
from m2riv.core.identity import fingerprint
from m2riv.metrics import ExactMatchMetric, MeanLatencyMetric
from m2riv.plugins.models import PluginKind, PluginManifest
from m2riv.plugins.registry import PluginRegistry


def builtin_metric_registry() -> PluginRegistry:
    metrics = (ExactMatchMetric(), MeanLatencyMetric())
    identity = tuple(
        {
            "id": metric.id,
            "direction": metric.direction,
            "binary": metric.binary,
            "unit": metric.unit,
        }
        for metric in metrics
    )
    manifest = PluginManifest(
        name="m2riv.builtin.metrics",
        version=__version__,
        kind=PluginKind.METRIC,
        config_fingerprint=fingerprint(identity, namespace="builtin-metric-plugin"),
        capabilities=frozenset(metric.id for metric in metrics),
    )
    registry = PluginRegistry()
    for metric in metrics:
        registry.register_metric(manifest, metric)
    return registry
