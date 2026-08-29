"""Content-addressed local cache for raw model observations."""

from __future__ import annotations

import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from m2riv.core.identity import canonical_json, fingerprint
from m2riv.core.models import EvalCase, Observation, RetentionMode, RuntimeProfile
from m2riv.execution.local import LOCAL_EXECUTOR_FINGERPRINT

MAX_CACHE_ENTRY_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CacheKey:
    """All execution inputs that can change a case observation."""

    snapshot_id: str
    case_id: str
    case_content_fingerprint: str
    runtime_profile: RuntimeProfile
    adapter_fingerprint: str
    executor_fingerprint: str = LOCAL_EXECUTOR_FINGERPRINT

    def __post_init__(self) -> None:
        if not self.adapter_fingerprint.strip() or "\x00" in self.adapter_fingerprint:
            raise ValueError("adapter_fingerprint must be non-blank and contain no NUL bytes")
        if not self.executor_fingerprint.strip() or "\x00" in self.executor_fingerprint:
            raise ValueError("executor_fingerprint must be non-blank and contain no NUL bytes")

    @classmethod
    def for_case(
        cls,
        *,
        snapshot_id: str,
        case: EvalCase,
        runtime_profile: RuntimeProfile,
        adapter_fingerprint: str,
        executor_fingerprint: str = LOCAL_EXECUTOR_FINGERPRINT,
    ) -> CacheKey:
        """Build a cache key without relying on a case's human-readable ID alone."""
        return cls(
            snapshot_id=snapshot_id,
            case_id=case.case_id,
            case_content_fingerprint=fingerprint(case, namespace="eval-case-content"),
            runtime_profile=runtime_profile,
            adapter_fingerprint=adapter_fingerprint,
            executor_fingerprint=executor_fingerprint,
        )

    @property
    def digest(self) -> str:
        """Return the stable digest used for the on-disk object name."""
        payload = {
            "snapshot_id": self.snapshot_id,
            "case_id": self.case_id,
            "case_content_fingerprint": self.case_content_fingerprint,
            "runtime_profile": self.runtime_profile,
            "adapter_fingerprint": self.adapter_fingerprint,
            "executor_fingerprint": self.executor_fingerprint,
        }
        return fingerprint(payload, namespace="observation-cache-key")


class _CacheEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cache_format: Literal["m2riv-observation-cache-v1"] = "m2riv-observation-cache-v1"
    key_digest: str
    observation: Observation


class ObservationCache:
    """A local cache whose entries become visible through an atomic replace."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def path_for(self, key: CacheKey) -> Path:
        """Resolve a key to its deterministic, sharded cache path."""
        digest = key.digest
        return self.root / digest[:2] / f"{digest}.json"

    @staticmethod
    def _is_reparse_or_symlink(path_stat: os.stat_result) -> bool:
        attributes = getattr(path_stat, "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        return stat.S_ISLNK(path_stat.st_mode) or bool(attributes & reparse_flag)

    @classmethod
    def _safe_shard(cls, path: Path) -> bool:
        try:
            shard_stat = path.lstat()
        except OSError:
            return False
        return stat.S_ISDIR(shard_stat.st_mode) and not cls._is_reparse_or_symlink(shard_stat)

    @classmethod
    def _safe_entry(cls, path: Path) -> os.stat_result | None:
        try:
            entry_stat = path.lstat()
        except OSError:
            return None
        if not stat.S_ISREG(entry_stat.st_mode) or cls._is_reparse_or_symlink(entry_stat):
            return None
        return entry_stat

    def _prepare_shard(self, shard: Path) -> None:
        if self.root.exists() or self.root.is_symlink():
            if not self._safe_shard(self.root):
                raise ValueError("cache root must be a regular local directory")
        else:
            missing: list[Path] = []
            cursor = self.root
            while not cursor.exists() and not cursor.is_symlink():
                missing.append(cursor)
                if cursor.parent == cursor:
                    break
                cursor = cursor.parent
            if not self._safe_shard(cursor):
                raise ValueError("cache parent must be a regular local directory")
            for directory in reversed(missing):
                directory.mkdir()
                if not self._safe_shard(directory):
                    raise ValueError("cache root changed during creation")

        if shard.exists() or shard.is_symlink():
            if not self._safe_shard(shard):
                raise ValueError("cache shard must be a regular local directory")
        else:
            shard.mkdir()
            if not self._safe_shard(shard):
                raise ValueError("cache shard changed during creation")

    def get(self, key: CacheKey) -> Observation | None:
        """Read a verified observation; malformed or inconsistent entries are misses."""
        path = self.path_for(key)
        if not self._safe_shard(self.root) or not self._safe_shard(path.parent):
            return None
        entry_stat = self._safe_entry(path)
        if entry_stat is None or entry_stat.st_size > MAX_CACHE_ENTRY_BYTES:
            return None
        try:
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            with os.fdopen(descriptor, "rb") as stream:
                opened_stat = os.fstat(stream.fileno())
                if (
                    not stat.S_ISREG(opened_stat.st_mode)
                    or opened_stat.st_size > MAX_CACHE_ENTRY_BYTES
                ):
                    return None
                payload = stream.read(MAX_CACHE_ENTRY_BYTES + 1)
            if len(payload) > MAX_CACHE_ENTRY_BYTES:
                return None
        except OSError:
            return None

        try:
            envelope = _CacheEnvelope.model_validate_json(payload)
        except (ValidationError, ValueError):
            return None

        observation = envelope.observation
        if envelope.key_digest != key.digest:
            return None
        if observation.snapshot_id != key.snapshot_id or observation.case_id != key.case_id:
            return None
        if observation.retention == RetentionMode.FULL:
            actual_digest = fingerprint(observation.output, namespace="observation-output")
            if actual_digest != observation.output_digest:
                return None
        return observation

    def put(self, key: CacheKey, observation: Observation) -> None:
        """Atomically persist an observation after checking its cache-key identity."""
        if observation.snapshot_id != key.snapshot_id or observation.case_id != key.case_id:
            raise ValueError("observation identity does not match its cache key")

        path = self.path_for(key)
        self._prepare_shard(path.parent)
        envelope = _CacheEnvelope(key_digest=key.digest, observation=observation)
        encoded = canonical_json(envelope)
        if len(encoded) > MAX_CACHE_ENTRY_BYTES:
            raise ValueError(f"cache envelope exceeds {MAX_CACHE_ENTRY_BYTES} byte limit")

        if not self._safe_shard(path.parent):
            raise ValueError("cache shard must be a regular local directory")
        existing = path.lstat() if path.exists() or path.is_symlink() else None
        if existing is not None and (
            not stat.S_ISREG(existing.st_mode) or self._is_reparse_or_symlink(existing)
        ):
            raise ValueError("cache entry target must be a regular file")

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=path.parent,
                prefix=f".{path.stem}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary_path = Path(stream.name)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            if not self._safe_shard(path.parent):
                raise ValueError("cache shard changed during write")
            os.replace(temporary_path, path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
