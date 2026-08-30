from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parents[1]


def _load_verifier() -> ModuleType:
    path = ROOT / "tools" / "verify_pypi_release.py"
    spec = importlib.util.spec_from_file_location("verify_pypi_release", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_hash_check_accepts_exact_wheel_and_sdist(tmp_path: Path) -> None:
    verifier = _load_verifier()
    (tmp_path / "merriv-1.0-py3-none-any.whl").write_bytes(b"wheel")
    (tmp_path / "merriv-1.0.tar.gz").write_bytes(b"sdist")

    local = verifier.local_distribution_hashes(tmp_path)
    payload = {
        "urls": [
            {
                "filename": filename,
                "packagetype": "bdist_wheel" if filename.endswith(".whl") else "sdist",
                "digests": {"sha256": digest},
            }
            for filename, digest in local.items()
        ]
    }

    verifier.compare_release(local, verifier.published_distribution_hashes(payload))


def test_release_hash_check_rejects_same_version_with_different_bytes(tmp_path: Path) -> None:
    verifier = _load_verifier()
    (tmp_path / "merriv-1.0-py3-none-any.whl").write_bytes(b"wheel")
    (tmp_path / "merriv-1.0.tar.gz").write_bytes(b"sdist")
    local = verifier.local_distribution_hashes(tmp_path)
    published = dict(local)
    published["merriv-1.0.tar.gz"] = "0" * 64

    with pytest.raises(ValueError, match="do not byte-match"):
        verifier.compare_release(local, published)


def test_release_hash_check_rejects_incomplete_local_bundle(tmp_path: Path) -> None:
    verifier = _load_verifier()
    (tmp_path / "merriv-1.0-py3-none-any.whl").write_bytes(b"wheel")

    with pytest.raises(ValueError, match="one wheel and one source distribution"):
        verifier.local_distribution_hashes(tmp_path)
