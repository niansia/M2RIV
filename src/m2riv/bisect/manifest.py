"""Safe checkpoint-status manifests for offline regression localization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from m2riv.bisect.engine import BisectStatus
from m2riv.io.loaders import InputFormatError, _load_jsonl


@dataclass(frozen=True, slots=True)
class CheckpointStatus:
    checkpoint: str
    status: BisectStatus


@dataclass(frozen=True, slots=True)
class CheckpointArtifact:
    checkpoint: str
    artifact: Path


def _safe_checkpoint(value: object, *, source: Path, line_number: int) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 256
        or any(ord(character) < 32 or 127 <= ord(character) < 160 for character in value)
    ):
        raise InputFormatError(
            f"{source}:{line_number}: checkpoint must be a safe non-blank identifier"
        )
    return value.strip()


def load_checkpoint_statuses(path: str | Path) -> tuple[CheckpointStatus, ...]:
    """Load ordered ``checkpoint``/``status`` JSONL rows with strict keys."""
    source = Path(path)
    records: list[CheckpointStatus] = []
    seen: set[str] = set()
    for line_number, row in _load_jsonl(source):
        if set(row) != {"checkpoint", "status"}:
            raise InputFormatError(
                f"{source}:{line_number}: row must contain only checkpoint and status"
            )
        checkpoint = row["checkpoint"]
        status = row["status"]
        checkpoint = _safe_checkpoint(checkpoint, source=source, line_number=line_number)
        if checkpoint in seen:
            raise InputFormatError(f"{source}:{line_number}: duplicate checkpoint {checkpoint!r}")
        if not isinstance(status, str):
            raise InputFormatError(f"{source}:{line_number}: status must be a string")
        try:
            normalized_status = BisectStatus(status.casefold())
        except ValueError as error:
            raise InputFormatError(
                f"{source}:{line_number}: unsupported checkpoint status"
            ) from error
        seen.add(checkpoint)
        records.append(CheckpointStatus(checkpoint, normalized_status))
    return tuple(records)


def load_checkpoint_artifacts(path: str | Path) -> tuple[CheckpointArtifact, ...]:
    """Load ordered checkpoint/artifact rows without executing commands from input."""
    source = Path(path)
    records: list[CheckpointArtifact] = []
    seen: set[str] = set()
    for line_number, row in _load_jsonl(source):
        if set(row) != {"checkpoint", "artifact"}:
            raise InputFormatError(
                f"{source}:{line_number}: row must contain only checkpoint and artifact"
            )
        checkpoint = _safe_checkpoint(
            row["checkpoint"], source=source, line_number=line_number
        )
        if checkpoint in seen:
            raise InputFormatError(f"{source}:{line_number}: duplicate checkpoint {checkpoint!r}")
        raw_artifact = row["artifact"]
        if (
            not isinstance(raw_artifact, str)
            or not raw_artifact.strip()
            or len(raw_artifact) > 4096
            or any(
                ord(character) < 32 or 127 <= ord(character) < 160
                for character in raw_artifact
            )
        ):
            raise InputFormatError(
                f"{source}:{line_number}: artifact must be a safe non-blank path"
            )
        artifact = Path(raw_artifact.strip())
        if not artifact.is_absolute():
            artifact = source.parent / artifact
        if not artifact.exists():
            raise InputFormatError(f"{source}:{line_number}: artifact does not exist")
        seen.add(checkpoint)
        records.append(CheckpointArtifact(checkpoint=checkpoint, artifact=artifact))
    return tuple(records)
