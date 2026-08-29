"""Example third-party metric plugin loaded explicitly by trusted host code."""

from __future__ import annotations

from dataclasses import dataclass

from m2riv.core.identity import fingerprint
from m2riv.engine import PairedCaseResult
from m2riv.gate import MetricDirection
from m2riv.plugins import PluginKind, PluginManifest, PluginRegistry


@dataclass(frozen=True, slots=True)
class OutputLengthMetric:
    id: str = "output_length"
    direction: MetricDirection = MetricDirection.LOWER_IS_BETTER
    binary: bool = False
    unit: str = "characters"

    def sample(self, pair: PairedCaseResult) -> tuple[float, float] | None:
        if not isinstance(pair.baseline.output, str) or not isinstance(pair.candidate.output, str):
            return None
        return float(len(pair.baseline.output)), float(len(pair.candidate.output))


def register(registry: PluginRegistry) -> None:
    """Register this package's trusted, already-imported metric instance."""
    metric = OutputLengthMetric()
    manifest = PluginManifest(
        name="example.output-length",
        version="0.1.0",
        kind=PluginKind.METRIC,
        config_fingerprint=fingerprint(
            {
                "metric": metric.id,
                "direction": metric.direction,
                "unit": metric.unit,
            },
            namespace="example-output-length-plugin",
        ),
        capabilities=frozenset({metric.id}),
    )
    registry.register_metric(manifest, metric)
