"""Verify the public MCR v1 content-identity vectors using only stdlib."""

from __future__ import annotations

import hashlib
import json
import struct
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from typed_values import materialize_typed_value

VECTORS = Path(__file__).with_name("golden-vectors.json")
FLOAT_VECTORS = Path(__file__).with_name("float-vectors.json")


def jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((jsonable(item) for item in value), key=repr)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    return value


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        jsonable(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def fingerprint(value: Any, namespace: str) -> str:
    domain = f"mcr:{namespace}:v1".encode()
    return hashlib.sha256(domain + b"\0" + canonical_json(value)).hexdigest()


def main() -> None:
    document = json.loads(VECTORS.read_text(encoding="utf-8"))
    for vector in document["vectors"]:
        source = vector.get("typed_value", vector.get("value"))
        value = materialize_typed_value(source)
        actual_json = canonical_json(value).decode()
        if actual_json != vector["canonical_json"]:
            raise SystemExit(f"canonical JSON mismatch: {vector['name']}")
        if fingerprint(value, vector["namespace"]) != vector["sha256"]:
            raise SystemExit(f"fingerprint mismatch: {vector['name']}")
    print(f"verified {len(document['vectors'])} MCR v1 identity vectors")

    float_document = json.loads(FLOAT_VECTORS.read_text(encoding="utf-8"))
    for vector in float_document["vectors"]:
        value = struct.unpack(">d", bytes.fromhex(vector["bits"]))[0]
        payload = {"value": value}
        if canonical_json(payload).decode() != vector["canonical_json"]:
            raise SystemExit(f"float canonical JSON mismatch: {vector['bits']}")
        if fingerprint(payload, "float-spelling-corpus") != vector["sha256"]:
            raise SystemExit(f"float fingerprint mismatch: {vector['bits']}")
    print(f"verified {len(float_document['vectors'])} binary64 spelling vectors")


if __name__ == "__main__":
    main()
