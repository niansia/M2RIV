"""Pluggable execution backends for local, remote, or custom fabrics."""

from merriv.execution.base import ExecutionBackend, ExecutorDescriptor
from merriv.execution.local import LOCAL_EXECUTOR_FINGERPRINT, LocalExecutor

__all__ = [
    "LOCAL_EXECUTOR_FINGERPRINT",
    "ExecutionBackend",
    "ExecutorDescriptor",
    "LocalExecutor",
]
