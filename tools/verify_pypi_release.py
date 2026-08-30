"""Verify that a PyPI release is absent or byte-identical to local distributions."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def local_distribution_hashes(directory: Path) -> dict[str, str]:
    files = sorted((*directory.glob("*.whl"), *directory.glob("*.tar.gz")))
    if len(files) != 2 or sum(path.suffix == ".whl" for path in files) != 1:
        raise ValueError("expected exactly one wheel and one source distribution")
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    }


def published_distribution_hashes(payload: dict[str, Any]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for item in payload.get("urls", []):
        if not isinstance(item, dict) or item.get("packagetype") not in {
            "bdist_wheel",
            "sdist",
        }:
            continue
        filename = item.get("filename")
        digests = item.get("digests")
        digest = digests.get("sha256") if isinstance(digests, dict) else None
        if not isinstance(filename, str) or not isinstance(digest, str):
            raise ValueError("PyPI release metadata omitted a distribution SHA-256")
        hashes[filename] = digest
    if not hashes:
        raise ValueError("PyPI release metadata contains no distributions")
    return hashes


def compare_release(local: dict[str, str], published: dict[str, str]) -> None:
    if local != published:
        local_names = sorted(local)
        published_names = sorted(published)
        raise ValueError(
            "published distributions do not byte-match this build: "
            f"local={local_names}, published={published_names}"
        )


def fetch_release(project: str, version: str) -> dict[str, Any] | None:
    url = f"https://pypi.org/pypi/{project}/{version}/json"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "merriv-release-finalizer/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("PyPI release metadata exceeded the response limit")
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("PyPI release metadata is not a JSON object")
    return payload


def verify(
    project: str,
    version: str,
    directory: Path,
    *,
    require_existing: bool,
    attempts: int,
    retry_delay: float,
) -> str:
    local = local_distribution_hashes(directory)
    for attempt in range(attempts):
        payload = fetch_release(project, version)
        if payload is not None:
            compare_release(local, published_distribution_hashes(payload))
            return "matching"
        if not require_existing:
            return "absent"
        if attempt + 1 < attempts:
            time.sleep(retry_delay)
    raise ValueError(f"{project} {version} was not visible on PyPI after {attempts} attempts")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("version")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--require-existing", action="store_true")
    parser.add_argument("--attempts", type=int, default=1)
    parser.add_argument("--retry-delay", type=float, default=3.0)
    arguments = parser.parse_args()
    if arguments.attempts < 1 or arguments.retry_delay < 0:
        parser.error("attempts must be positive and retry-delay must be non-negative")
    try:
        state = verify(
            arguments.project,
            arguments.version,
            arguments.directory,
            require_existing=arguments.require_existing,
            attempts=arguments.attempts,
            retry_delay=arguments.retry_delay,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"PyPI release verification failed: {error}", file=sys.stderr)
        return 1
    print(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
