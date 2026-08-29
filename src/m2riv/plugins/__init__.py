"""Stable SDK surface for explicit M2RIV plugin registration."""

from m2riv.plugins.builtin import builtin_metric_registry
from m2riv.plugins.models import PluginKind, PluginManifest
from m2riv.plugins.registry import (
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
