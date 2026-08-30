"""Paired metric plugin contracts and dependency-free built-ins."""

from merriv.metrics.base import PairedMetric
from merriv.metrics.builtin import ExactMatchMetric, MeanLatencyMetric

__all__ = ["ExactMatchMetric", "MeanLatencyMetric", "PairedMetric"]
