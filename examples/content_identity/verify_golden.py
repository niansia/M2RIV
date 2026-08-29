"""Verify the public M2RIV v1 content-identity vectors using only stdlib."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

VECTORS = Path(__file__).with_name("golden-vectors.json")


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def fingerprint(value: Any, namespace: str) -> str:
    domain = f"m2riv:{namespace}:v1".encode()
    return hashlib.sha256(domain + b"\0" + canonical_json(value)).hexdigest()


def main() -> None:
    document = json.loads(VECTORS.read_text(encoding="utf-8"))
    for vector in document["vectors"]:
        actual_json = canonical_json(vector["value"]).decode()
        if actual_json != vector["canonical_json"]:
            raise SystemExit(f"canonical JSON mismatch: {vector['name']}")
        if fingerprint(vector["value"], vector["namespace"]) != vector["sha256"]:
            raise SystemExit(f"fingerprint mismatch: {vector['name']}")
    print(f"verified {len(document['vectors'])} M2RIV v1 identity vectors")


if __name__ == "__main__":
    main()
