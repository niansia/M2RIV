"""Pluggable execution backends for local, Ray, Kubernetes, or custom fabrics."""

from m2riv.execution.base import ExecutionBackend, ExecutorDescriptor
from m2riv.execution.local import LOCAL_EXECUTOR_FINGERPRINT, LocalExecutor

__all__ = [
    "LOCAL_EXECUTOR_FINGERPRINT",
    "ExecutionBackend",
    "ExecutorDescriptor",
    "LocalExecutor",
]
