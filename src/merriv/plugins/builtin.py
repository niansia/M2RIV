"""Canonical registry containing dependency-free Merriv metrics."""

from __future__ import annotations

from merriv import __version__
from merriv.core.identity import fingerprint
from merriv.metrics import ExactMatchMetric, MeanLatencyMetric
from merriv.plugins.models import PluginKind, PluginManifest
from merriv.plugins.registry import PluginRegistry


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
        name="merriv.builtin.metrics",
        version=__version__,
        kind=PluginKind.METRIC,
        config_fingerprint=fingerprint(identity, namespace="builtin-metric-plugin"),
        capabilities=frozenset(metric.id for metric in metrics),
    )
    registry = PluginRegistry()
    for metric in metrics:
        registry.register_metric(manifest, metric)
    return registry
