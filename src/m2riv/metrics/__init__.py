"""Paired metric plugin contracts and dependency-free built-ins."""

from m2riv.metrics.base import PairedMetric
from m2riv.metrics.builtin import ExactMatchMetric, MeanLatencyMetric

__all__ = ["ExactMatchMetric", "MeanLatencyMetric", "PairedMetric"]
