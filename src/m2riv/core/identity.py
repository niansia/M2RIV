"""Content identity primitives with explicit domain separation."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Mapping
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from m2riv.core.models import (
    ArtifactDigest,
    EvidenceAccess,
    ModelFamily,
    ModelRef,
    ModelSnapshot,
    RuntimeProfile,
)

_CHUNK_SIZE = 1024 * 1024
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024 * 1024
MAX_ARTIFACT_FILE_BYTES = 16 * 1024 * 1024 * 1024
MAX_ARTIFACT_ENTRIES = 100_000


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        # Keep Python containers intact until the canonicalizer has sorted
        # unordered values. Pydantic's JSON mode eagerly turns frozensets into
        # lists, preserving hash-table iteration order across that boundary.
        return _jsonable(value.model_dump(mode="python", exclude_none=False))
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("canonical JSON object keys must be strings")
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_jsonable(item) for item in value), key=repr)
    if isinstance(value, Enum):
        return _jsonable(value.value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("canonical datetimes must be timezone-aware")
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    return value


def canonical_json(value: Any) -> bytes:
    """Serialize JSON deterministically for portable fingerprints."""
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def fingerprint(value: Any, *, namespace: str) -> str:
    """Hash a value under a namespace to prevent cross-protocol collisions."""
    if not namespace or "\x00" in namespace:
        raise ValueError("namespace must be non-empty and contain no NUL bytes")
    digest = hashlib.sha256()
    digest.update(f"m2riv:{namespace}:v1".encode())
    digest.update(b"\x00")
    digest.update(canonical_json(value))
    return digest.hexdigest()


def _hash_file(path: Path, *, max_bytes: int) -> tuple[str, int]:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f"artifact entry must be a regular file: {path}")
    if before.st_size > max_bytes:
        raise ValueError(f"artifact file exceeds the {max_bytes} byte budget: {path}")

    digest = hashlib.sha256()
    size = 0
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError(f"artifact entry must be a regular file: {path}")
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError(f"artifact changed while being opened: {path}")

        while chunk := os.read(descriptor, min(_CHUNK_SIZE, max_bytes - size + 1)):
            digest.update(chunk)
            size += len(chunk)
            if size > max_bytes:
                raise ValueError(f"artifact file exceeds the {max_bytes} byte budget: {path}")

        after = os.fstat(descriptor)
        if (
            opened.st_size != after.st_size
            or opened.st_mtime_ns != after.st_mtime_ns
            or size != after.st_size
        ):
            raise ValueError(f"artifact changed while being hashed: {path}")
    finally:
        os.close(descriptor)
    return digest.hexdigest(), size


def _is_link_like(path: Path) -> bool:
    is_junction = getattr(os.path, "isjunction", None)
    return path.is_symlink() or bool(is_junction and is_junction(path))


def hash_artifact(
    path: str | Path,
    *,
    max_total_bytes: int = MAX_ARTIFACT_BYTES,
    max_file_bytes: int = MAX_ARTIFACT_FILE_BYTES,
    max_entries: int = MAX_ARTIFACT_ENTRIES,
) -> ArtifactDigest:
    """Hash a file or directory without including its absolute location."""
    for name, value in (
        ("max_total_bytes", max_total_bytes),
        ("max_file_bytes", max_file_bytes),
        ("max_entries", max_entries),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    artifact = Path(path)
    if not artifact.exists():
        raise FileNotFoundError(artifact)
    if _is_link_like(artifact):
        raise ValueError("symbolic-link artifacts are rejected; resolve them explicitly")

    if artifact.is_file():
        digest, size = _hash_file(
            artifact, max_bytes=min(max_total_bytes, max_file_bytes)
        )
        return ArtifactDigest(digest=digest, size_bytes=size, logical_name=artifact.name)

    if not artifact.is_dir():
        raise ValueError(f"artifact must be a regular file or directory: {artifact}")

    candidates: list[Path] = []
    for entry_count, candidate in enumerate(artifact.rglob("*"), start=1):
        if entry_count > max_entries:
            raise ValueError(f"artifact exceeds the {max_entries} entry traversal budget")
        candidates.append(candidate)

    entries: list[tuple[str, str, int]] = []
    total_size = 0
    for candidate in sorted(candidates, key=lambda p: p.as_posix()):
        if _is_link_like(candidate):
            raise ValueError(f"symbolic link inside artifact is not allowed: {candidate}")
        candidate_stat = candidate.lstat()
        if stat.S_ISDIR(candidate_stat.st_mode):
            continue
        if not stat.S_ISREG(candidate_stat.st_mode):
            raise ValueError(f"artifact entry must be a regular file: {candidate}")
        remaining = max_total_bytes - total_size
        file_digest, size = _hash_file(
            candidate, max_bytes=min(max_file_bytes, max(0, remaining))
        )
        relative = candidate.relative_to(artifact).as_posix()
        entries.append((relative, file_digest, size))
        total_size += size

    if not entries:
        raise ValueError("artifact directory must contain at least one file")
    digest = fingerprint(entries, namespace="artifact-directory")
    return ArtifactDigest(
        digest=digest,
        size_bytes=total_size,
        file_count=len(entries),
        logical_name=artifact.name,
    )


def build_local_snapshot(
    path: str | Path,
    *,
    model_family: ModelFamily = ModelFamily.CUSTOM,
    runtime_profile: RuntimeProfile | None = None,
    execution_config: dict[str, Any] | None = None,
    labels: dict[str, str] | None = None,
    max_artifact_bytes: int = MAX_ARTIFACT_BYTES,
    max_artifact_file_bytes: int = MAX_ARTIFACT_FILE_BYTES,
    max_artifact_entries: int = MAX_ARTIFACT_ENTRIES,
) -> ModelSnapshot:
    """Resolve a local reference into a portable content-addressed snapshot."""
    artifact = Path(path)
    profile = runtime_profile or RuntimeProfile()
    config = execution_config or {}
    artifact_digest = hash_artifact(
        artifact,
        max_total_bytes=max_artifact_bytes,
        max_file_bytes=max_artifact_file_bytes,
        max_entries=max_artifact_entries,
    )
    config_digest = fingerprint(
        {"runtime_profile": profile, "execution_config": config},
        namespace="execution-config",
    )
    identity_payload = {
        "artifacts": [artifact_digest.model_dump(exclude={"logical_name"})],
        "config_fingerprint": config_digest,
    }
    snapshot_digest = fingerprint(identity_payload, namespace="model-snapshot")
    source_uri = os.fspath(artifact)
    return ModelSnapshot(
        id=f"m2riv:sha256:{snapshot_digest}",
        source=ModelRef(uri=source_uri),
        model_family=model_family,
        artifact_hashes=(artifact_digest,),
        config_fingerprint=config_digest,
        runtime_profile=profile,
        labels=labels or {},
        evidence_access=EvidenceAccess.ARTIFACTS,
    )
