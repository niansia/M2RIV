"""Versioned, immutable public contracts for Model Release Engineering."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from math import isfinite
from typing import Annotated, Any, Literal
from unicodedata import bidirectional

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
# Content identity belongs to the MCR protocol, not to the current reference
# implementation or its provisional brand.
ContentId = Annotated[str, StringConstraints(pattern=r"^mcr:sha256:[a-f0-9]{64}$")]
SafePluginName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]
SafePluginVersion = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9.+_-]{0,63}$")]
SafePluginCapability = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
]

_BIDI_CONTROL_CLASSES = frozenset({"LRE", "RLE", "LRO", "RLO", "PDF", "LRI", "RLI", "FSI", "PDI"})


def _validate_case_id(value: str) -> str:
    if value != value.strip():
        raise ValueError("case_id must not have leading or trailing whitespace")
    if any(not character.isprintable() for character in value):
        raise ValueError("case_id must contain only printable characters")
    if any(bidirectional(character) in _BIDI_CONTROL_CLASSES for character in value):
        raise ValueError("case_id must not contain Unicode bidi controls")
    return value


SafeCaseId = Annotated[
    str,
    StringConstraints(min_length=1, max_length=256),
    AfterValidator(_validate_case_id),
]

_SENSITIVE_CONFIG_KEYS = frozenset(
    {
        "apikey",
        "authorization",
        "bearertoken",
        "clientsecret",
        "headers",
        "password",
        "refreshtoken",
        "secret",
        "token",
    }
)


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""
    return datetime.now(UTC)


def _reject_non_finite_numbers(value: Any, *, field_name: str) -> Any:
    """Reject NaN/Infinity recursively before they can poison JSON evidence."""
    if isinstance(value, float) and not isfinite(value):
        raise ValueError(f"{field_name} must not contain NaN or Infinity")
    if isinstance(value, dict):
        for item in value.values():
            _reject_non_finite_numbers(item, field_name=field_name)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _reject_non_finite_numbers(item, field_name=field_name)
    return value


def _reject_sensitive_config(value: Any, *, field_name: str) -> Any:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = "".join(
                character for character in str(key).casefold() if character.isalnum()
            )
            if normalized in _SENSITIVE_CONFIG_KEYS:
                raise ValueError(f"{field_name} must not contain credentials or headers")
            _reject_sensitive_config(item, field_name=field_name)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_sensitive_config(item, field_name=field_name)
    return value


class Contract(BaseModel):
    """Strict and immutable base for all portable M2RIV contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=False)


class ModelFamily(StrEnum):
    LLM = "llm"
    VLM = "vlm"
    CV = "cv"
    EMBEDDING = "embedding"
    SPEECH = "speech"
    CUSTOM = "custom"


class EvidenceAccess(StrEnum):
    DECLARED = "declared"
    OUTPUTS = "outputs"
    LOGPROBS = "logprobs"
    INTERNALS = "internals"
    ARTIFACTS = "artifacts"


class ClaimStrength(StrEnum):
    DESCRIPTIVE = "descriptive"
    OBSERVED = "observed"
    STATISTICAL = "statistical"
    CAUSAL = "causal"


class RetentionMode(StrEnum):
    FULL = "full"
    REDACTED = "redacted"
    HASH_ONLY = "hash_only"


class ModelRef(Contract):
    """A source reference. Resolution into a snapshot happens separately."""

    uri: Annotated[str, StringConstraints(min_length=1)]
    revision: str | None = None

    @field_validator("uri")
    @classmethod
    def reject_ambiguous_uri(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("model reference must not be blank")
        if "\x00" in value:
            raise ValueError("model reference must not contain NUL bytes")
        return value


class RuntimeProfile(Contract):
    """Execution-relevant settings that participate in snapshot identity."""

    seed: int = 0
    deterministic: bool = True
    repetitions: Annotated[int, Field(ge=1)] = 1
    framework: str | None = None
    framework_version: str | None = None
    device: str | None = None
    dtype: str | None = None
    operating_system: str | None = None
    architecture: str | None = None
    python_version: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("parameters")
    @classmethod
    def parameters_must_be_finite(cls, value: dict[str, Any]) -> dict[str, Any]:
        _reject_non_finite_numbers(value, field_name="parameters")
        _reject_sensitive_config(value, field_name="parameters")
        return value


class ArtifactDigest(Contract):
    """Digest and metadata for a local artifact without location-dependent identity."""

    algorithm: Literal["sha256"] = "sha256"
    digest: Digest
    size_bytes: Annotated[int, Field(ge=0)]
    file_count: Annotated[int, Field(ge=1)] = 1
    logical_name: str | None = None


class ModelSnapshot(Contract):
    """A reproducible, comparable model state."""

    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    id: ContentId
    source: ModelRef
    model_family: ModelFamily = ModelFamily.CUSTOM
    artifact_hashes: tuple[ArtifactDigest, ...] = ()
    config_fingerprint: Digest
    runtime_profile: RuntimeProfile = Field(default_factory=RuntimeProfile)
    code_revision: str | None = None
    data_revision: str | None = None
    parent_snapshot: ContentId | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    capabilities: frozenset[str] = frozenset()
    evidence_access: EvidenceAccess = EvidenceAccess.DECLARED


class EvalCase(Contract):
    """One replayable, pairable evaluation unit."""

    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    case_id: SafeCaseId
    input: Any
    expected: Any | None = None
    contract: dict[str, Any] | None = None
    tags: frozenset[str] = frozenset()
    slices: dict[str, str] = Field(default_factory=dict)
    critical: bool = False

    @field_validator("input", "expected", "contract")
    @classmethod
    def payload_numbers_must_be_finite(cls, value: Any, info: Any) -> Any:
        return _reject_non_finite_numbers(value, field_name=info.field_name)


class EvidenceRef(Contract):
    """A content-addressed evidence edge used by claims and decisions."""

    id: ContentId
    kind: Annotated[str, StringConstraints(min_length=1)]
    media_type: str = "application/json"
    uri: str | None = None
    redacted: bool = False


class Observation(Contract):
    """Raw evidence produced by running one snapshot on one case."""

    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    id: ContentId
    snapshot_id: ContentId
    case_id: SafeCaseId
    attempt: Annotated[int, Field(ge=0)] = 0
    seed: int | None = None
    output: Any | None = None
    output_digest: Digest
    latency_ms: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    traces: dict[str, Any] = Field(default_factory=dict)
    retention: RetentionMode = RetentionMode.FULL
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("output", "traces")
    @classmethod
    def evidence_numbers_must_be_finite(cls, value: Any, info: Any) -> Any:
        return _reject_non_finite_numbers(value, field_name=info.field_name)

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def hash_only_must_not_retain_plaintext(self) -> Observation:
        if self.retention == RetentionMode.HASH_ONLY and (self.output is not None or self.traces):
            raise ValueError("hash_only observations must not retain output or traces")
        return self


class Claim(Contract):
    """A conclusion whose strength cannot exceed its linked evidence."""

    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    id: ContentId
    claim_type: Annotated[str, StringConstraints(min_length=1)]
    statement: Annotated[str, StringConstraints(min_length=1)]
    strength: ClaimStrength
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = ()


class PluginRecord(Contract):
    """Exact plugin provenance captured for replay and audit."""

    name: SafePluginName
    version: SafePluginVersion
    kind: Literal["adapter", "metric", "executor", "unknown"] = "unknown"
    api_version: SafePluginVersion = "0.1"
    capabilities: frozenset[SafePluginCapability] = Field(default_factory=frozenset, max_length=64)
    config_fingerprint: Digest


class RunManifest(Contract):
    """Immutable provenance for one paired comparison run."""

    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    run_id: ContentId
    created_at: datetime = Field(default_factory=utc_now)
    baseline_snapshot_id: ContentId
    candidate_snapshot_ids: tuple[ContentId, ...] = Field(min_length=1)
    suite_fingerprint: Digest
    config_fingerprint: Digest
    code_revision: str | None = None
    environment: dict[str, str] = Field(default_factory=dict)
    dependencies: dict[str, str] = Field(default_factory=dict)
    plugins: tuple[PluginRecord, ...] = Field(default=(), max_length=128)
    seed: int = 0
    case_count: Annotated[int, Field(ge=0)] = 0

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value
