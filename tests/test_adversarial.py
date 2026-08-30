from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from merriv.core import identity
from merriv.core.identity import fingerprint, hash_artifact
from merriv.core.models import EvalCase, Observation, RetentionMode, RuntimeProfile


def _content_id(label: str) -> str:
    return f"mcr:sha256:{fingerprint(label, namespace='adversarial-test')}"


def _observation(**overrides: object) -> Observation:
    values: dict[str, object] = {
        "id": _content_id("observation"),
        "snapshot_id": _content_id("snapshot"),
        "case_id": "case-1",
        "output": None,
        "output_digest": fingerprint(None, namespace="observation-output"),
    }
    values.update(overrides)
    return Observation.model_validate(values)


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_numbers_cannot_enter_evidence(bad_value: float) -> None:
    with pytest.raises(ValidationError, match="NaN or Infinity"):
        _observation(output={"nested": [bad_value]})

    with pytest.raises(ValidationError, match="NaN or Infinity"):
        EvalCase(case_id="poison", input={"score": bad_value})

    with pytest.raises(ValidationError, match="NaN or Infinity"):
        RuntimeProfile(parameters={"temperature": bad_value})


@pytest.mark.parametrize("bad_latency", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_latency_cannot_poison_aggregates(bad_latency: float) -> None:
    with pytest.raises(ValidationError):
        _observation(latency_ms=bad_latency)


def test_hash_only_retention_cannot_carry_plaintext_output() -> None:
    with pytest.raises(ValidationError, match="must not retain output or traces"):
        _observation(
            retention=RetentionMode.HASH_ONLY,
            output={"authorization": "Bearer secret"},
        )

    with pytest.raises(ValidationError, match="must not retain output or traces"):
        _observation(
            retention=RetentionMode.HASH_ONLY,
            traces={"prompt": "private training example"},
        )

    assert _observation(retention=RetentionMode.HASH_ONLY).output is None


def test_canonical_fingerprint_rejects_nan_instead_of_aliasing_json() -> None:
    with pytest.raises(ValueError, match="Out of range float values"):
        fingerprint({"metric": float("nan")}, namespace="metric")


def test_top_level_symlink_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "weights.bin"
    link = tmp_path / "weights-link.bin"
    target.write_bytes(b"trusted")
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip("creating symlinks is not supported in this environment")

    with pytest.raises(ValueError, match="symbolic-link artifacts"):
        hash_artifact(link)


def test_symlink_inside_directory_is_rejected(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact"
    outside = tmp_path / "outside.bin"
    link = artifact / "weights.bin"
    artifact.mkdir()
    outside.write_bytes(b"mutable-outside-content")
    try:
        link.symlink_to(outside)
    except (NotImplementedError, OSError):
        pytest.skip("creating symlinks is not supported in this environment")

    with pytest.raises(ValueError, match="symbolic link inside artifact"):
        hash_artifact(artifact)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are not available on this OS")
def test_special_file_is_not_accepted_as_artifact(tmp_path: Path) -> None:
    fifo = tmp_path / "model.pipe"
    os.mkfifo(fifo)

    with pytest.raises(ValueError, match="regular file or directory"):
        hash_artifact(fifo)


def test_file_change_during_hash_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = tmp_path / "weights.bin"
    artifact.write_bytes(b"weights")
    real_fstat = identity.os.fstat
    calls = 0

    def changing_fstat(descriptor: int) -> os.stat_result:
        nonlocal calls
        result = real_fstat(descriptor)
        calls += 1
        if calls == 2:
            values = list(result)
            values[8] += 1  # st_mtime is index 8 in os.stat_result.
            return os.stat_result(values)
        return result

    monkeypatch.setattr(identity.os, "fstat", changing_fstat)
    with pytest.raises(ValueError, match="changed while being hashed"):
        hash_artifact(artifact)
