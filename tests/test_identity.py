from __future__ import annotations

from pathlib import Path

import pytest

from m2riv.core.identity import build_local_snapshot, hash_artifact
from m2riv.core.models import RuntimeProfile


def test_same_file_content_has_same_identity_across_paths(tmp_path: Path) -> None:
    first = tmp_path / "first.bin"
    second = tmp_path / "elsewhere" / "renamed.bin"
    first.write_bytes(b"model-weights")
    second.parent.mkdir()
    second.write_bytes(b"model-weights")

    assert hash_artifact(first).digest == hash_artifact(second).digest
    assert build_local_snapshot(first).id == build_local_snapshot(second).id


def test_execution_config_changes_snapshot_identity(tmp_path: Path) -> None:
    artifact = tmp_path / "model.bin"
    artifact.write_bytes(b"model-weights")

    fp16 = build_local_snapshot(artifact, runtime_profile=RuntimeProfile(dtype="float16"))
    int8 = build_local_snapshot(artifact, runtime_profile=RuntimeProfile(dtype="int8"))

    assert fp16.id != int8.id
    assert fp16.artifact_hashes[0].digest == int8.artifact_hashes[0].digest


def test_directory_hash_is_stable_and_structure_sensitive(tmp_path: Path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    for root in (left, right):
        (root / "config").mkdir(parents=True)
        (root / "weights.bin").write_bytes(b"weights")
        (root / "config" / "model.json").write_text('{"layers": 2}', encoding="utf-8")

    assert hash_artifact(left).digest == hash_artifact(right).digest
    (right / "config" / "model.json").write_text('{"layers": 3}', encoding="utf-8")
    assert hash_artifact(left).digest != hash_artifact(right).digest


def test_large_files_are_streamed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact = tmp_path / "large.bin"
    artifact.write_bytes(b"x" * (2 * 1024 * 1024 + 17))

    from m2riv.core import identity

    monkeypatch.setattr(identity, "_CHUNK_SIZE", 64 * 1024)
    result = hash_artifact(artifact)
    assert result.size_bytes == artifact.stat().st_size
    assert len(result.digest) == 64


def test_empty_directory_is_not_an_artifact(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least one file"):
        hash_artifact(tmp_path)


def test_artifact_hashing_enforces_byte_file_and_traversal_budgets(tmp_path: Path) -> None:
    large = tmp_path / "large.bin"
    large.write_bytes(b"12345")
    with pytest.raises(ValueError, match="byte budget"):
        hash_artifact(large, max_total_bytes=4)
    with pytest.raises(ValueError, match="byte budget"):
        hash_artifact(large, max_file_bytes=4)

    artifact = tmp_path / "directory"
    artifact.mkdir()
    (artifact / "a.bin").write_bytes(b"123")
    (artifact / "b.bin").write_bytes(b"456")
    with pytest.raises(ValueError, match="byte budget"):
        hash_artifact(artifact, max_total_bytes=5)
    with pytest.raises(ValueError, match="entry traversal budget"):
        hash_artifact(artifact, max_entries=1)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("max_total_bytes", 0),
        ("max_file_bytes", -1),
        ("max_entries", True),
    ],
)
def test_artifact_hashing_rejects_invalid_budgets(
    tmp_path: Path, name: str, value: int
) -> None:
    artifact = tmp_path / "model.bin"
    artifact.write_bytes(b"model")
    arguments = {name: value}
    with pytest.raises(ValueError, match="positive integer"):
        hash_artifact(artifact, **arguments)  # type: ignore[arg-type]


def test_sparse_file_is_rejected_from_metadata_before_content_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = tmp_path / "sparse.bin"
    with artifact.open("wb") as stream:
        stream.truncate(1024 * 1024)

    def unexpected_open(*args: object, **kwargs: object) -> int:
        raise AssertionError("oversized sparse file must not be opened")

    from m2riv.core import identity

    monkeypatch.setattr(identity.os, "open", unexpected_open)
    with pytest.raises(ValueError, match="byte budget"):
        hash_artifact(artifact, max_total_bytes=1024)
