"""Explicit plugin manifests; registration never imports code implicitly."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from merriv.core.models import Contract, Digest

SafePluginName = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"),
]
SafeVersion = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9.+_-]{0,63}$"),
]
SafeCapability = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"),
]


class PluginKind(StrEnum):
    ADAPTER = "adapter"
    EXECUTOR = "executor"
    METRIC = "metric"


class PluginManifest(Contract):
    """Non-secret identity and compatibility declaration for one plugin package."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    name: SafePluginName
    version: SafeVersion
    api_version: Literal["0.1"] = "0.1"
    kind: PluginKind
    config_fingerprint: Digest
    capabilities: frozenset[SafeCapability] = Field(default_factory=frozenset, max_length=64)
