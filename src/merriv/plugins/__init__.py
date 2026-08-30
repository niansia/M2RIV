"""Stable SDK surface for explicit Merriv plugin registration."""

from merriv.plugins.builtin import builtin_metric_registry
from merriv.plugins.models import PluginKind, PluginManifest
from merriv.plugins.registry import (
    MAX_REGISTERED_ADAPTERS,
    MAX_REGISTERED_EXECUTORS,
    MAX_REGISTERED_METRICS,
    MAX_REGISTERED_PLUGINS,
    MetricDeclaration,
    PluginRegistrationError,
    PluginRegistry,
    RegisteredAdapter,
    RegisteredExecutor,
    RegisteredMetric,
)

__all__ = [
    "MAX_REGISTERED_ADAPTERS",
    "MAX_REGISTERED_EXECUTORS",
    "MAX_REGISTERED_METRICS",
    "MAX_REGISTERED_PLUGINS",
    "MetricDeclaration",
    "PluginKind",
    "PluginManifest",
    "PluginRegistrationError",
    "PluginRegistry",
    "RegisteredAdapter",
    "RegisteredExecutor",
    "RegisteredMetric",
    "builtin_metric_registry",
]
