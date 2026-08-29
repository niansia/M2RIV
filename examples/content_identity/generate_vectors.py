"""Generate the public M2RIV v1 identity conformance vectors."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from typed_values import materialize_typed_value

DESTINATION = Path(__file__).with_name("golden-vectors.json")
FLOAT_DESTINATION = Path(__file__).with_name("float-vectors.json")
FLOAT_VECTOR_COUNT = 1024


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_jsonable(item) for item in value), key=repr)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    return value


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _vector(
    name: str,
    namespace: str,
    *,
    value: Any | None = None,
    typed_value: Any | None = None,
) -> dict[str, Any]:
    if (value is None) == (typed_value is None):
        raise ValueError("a vector must define exactly one value representation")
    source = typed_value if typed_value is not None else value
    materialized = materialize_typed_value(source)
    canonical = _canonical_json(materialized)
    domain = f"m2riv:{namespace}:v1".encode()
    result: dict[str, Any] = {"name": name, "namespace": namespace}
    result["typed_value" if typed_value is not None else "value"] = source
    result["canonical_json"] = canonical.decode()
    result["sha256"] = hashlib.sha256(domain + b"\0" + canonical).hexdigest()
    return result


def build_document() -> dict[str, Any]:
    vectors = [
        _vector(
            "object-order-unicode",
            "golden-basic",
            value={"z": None, "a": "M2RIV", "unicode": "模型"},
        ),
        _vector(
            "numbers-and-arrays",
            "golden-numbers",
            value={"values": [-0.0, 0.5, -1.25, 42, True, False, None]},
        ),
        _vector(
            "nested-escaping",
            "golden-nested",
            value={
                "outer": {"line": "one\ntwo", "quote": '"', "slash": "a/b"},
                "array": [{"b": 2, "a": 1}, "é"],
            },
        ),
        _vector(
            "integer-versus-integral-float",
            "typed-number-kind",
            typed_value={
                "integer": {"$integer": "1"},
                "float": {"$float64": "3ff0000000000000"},
            },
        ),
        _vector(
            "signed-zero",
            "typed-signed-zero",
            typed_value={
                "negative": {"$float64": "8000000000000000"},
                "positive": {"$float64": "0000000000000000"},
            },
        ),
        _vector(
            "smallest-subnormal",
            "typed-subnormal",
            typed_value={"value": {"$float64": "0000000000000001"}},
        ),
        _vector(
            "smallest-normal",
            "typed-normal",
            typed_value={"value": {"$float64": "0010000000000000"}},
        ),
        _vector(
            "largest-finite",
            "typed-max-finite",
            typed_value={"value": {"$float64": "7fefffffffffffff"}},
        ),
        _vector(
            "python-fixed-lower-boundary",
            "typed-fixed-lower",
            typed_value={
                "fixed": {"$float64": "3f1a36e2eb1c432d"},
                "scientific": {"$float64": "3ee4f8b588e368f1"},
            },
        ),
        _vector(
            "python-fixed-upper-boundary",
            "typed-fixed-upper",
            typed_value={
                "fixed": {"$float64": "430c6bf526340000"},
                "scientific": {"$float64": "4341c37937e08000"},
            },
        ),
        _vector(
            "hard-round-trip-values",
            "typed-round-trip",
            typed_value={
                "decimal_sum": {"$float64": "3fd3333333333334"},
                "small": {"$float64": "3e8091f1667f0595"},
                "large": {"$float64": "441ac53a7e04bcd9"},
            },
        ),
        _vector(
            "unicode-scalar-key-order",
            "typed-unicode-order",
            typed_value={"😀": "astral", "\ue000": "private-use", "a": "ascii"},
        ),
        _vector(
            "unicode-no-normalization",
            "typed-unicode-normalization",
            typed_value={"composed": "é", "decomposed": "é", "emoji": "🧪"},
        ),
        _vector(
            "utc-datetime-normalization",
            "typed-datetime-utc",
            typed_value={"created_at": {"$datetime": "2026-08-29T12:34:56.123456Z"}},
        ),
        _vector(
            "offset-datetime-preservation",
            "typed-datetime-offset",
            typed_value={"created_at": {"$datetime": "2026-08-29T20:34:56+08:00"}},
        ),
        _vector(
            "portable-path",
            "typed-path",
            typed_value={"path": {"$path": "artifacts\\engine\\model.plan"}},
        ),
        _vector(
            "portable-string-set",
            "typed-set",
            typed_value={"capabilities": {"$set": ["zeta", "alpha", "beta", "alpha"]}},
        ),
        _vector(
            "explicit-null-and-defaults",
            "typed-defaults",
            typed_value={
                "required": "value",
                "optional": None,
                "defaults": {"enabled": False, "count": {"$integer": "0"}, "items": []},
            },
        ),
        _vector(
            "safe-integer-boundaries",
            "typed-integers",
            typed_value={
                "javascript_safe_max": {"$integer": "9007199254740991"},
                "signed_min": {"$integer": "-9223372036854775808"},
            },
        ),
        _vector(
            "control-and-separator-escaping",
            "typed-escaping",
            typed_value={"control": "\b\f\n\r\t\u0000", "separators": "\u2028\u2029"},
        ),
    ]
    return {
        "schema_version": "1.1.0",
        "canonicalization_version": "v1",
        "algorithm": "sha256",
        "typed_value_notation": {
            "$float64": "16 lowercase hexadecimal IEEE-754 binary64 bits",
            "$integer": "base-10 integer string",
            "$datetime": "offset-aware RFC 3339 string converted to typed datetime",
            "$path": "path converted to POSIX separators",
            "$set": "portable string set sorted by Unicode scalar value",
        },
        "vectors": vectors,
    }


def build_float_document() -> dict[str, Any]:
    bit_patterns = [
        0x0000000000000000,
        0x8000000000000000,
        0x0000000000000001,
        0x0010000000000000,
        0x7FEFFFFFFFFFFFFF,
        0x3FF0000000000000,
        0x3F1A36E2EB1C432D,
        0x3EE4F8B588E368F1,
        0x430C6BF526340000,
        0x4341C37937E08000,
        0x3FD3333333333334,
    ]
    seen = set(bit_patterns)
    counter = 0
    while len(bit_patterns) < FLOAT_VECTOR_COUNT:
        candidate = int.from_bytes(
            hashlib.sha256(b"m2riv-f64-v1\0" + counter.to_bytes(8, "big")).digest()[:8],
            "big",
        )
        counter += 1
        if candidate in seen or (candidate >> 52) & 0x7FF == 0x7FF:
            continue
        seen.add(candidate)
        bit_patterns.append(candidate)

    vectors = []
    for bits in bit_patterns:
        value = struct.unpack(">d", bits.to_bytes(8, "big"))[0]
        payload = {"value": value}
        canonical = _canonical_json(payload)
        domain = b"m2riv:float-spelling-corpus:v1"
        vectors.append(
            {
                "bits": f"{bits:016x}",
                "canonical_json": canonical.decode(),
                "sha256": hashlib.sha256(domain + b"\0" + canonical).hexdigest(),
            }
        )
    return {
        "schema_version": "1.0.0",
        "canonicalization_version": "v1",
        "algorithm": "sha256",
        "generation": "11 anchors plus SHA-256(m2riv-f64-v1\\0 || uint64be(counter))",
        "vectors": vectors,
    }


def render() -> str:
    return json.dumps(build_document(), ensure_ascii=False, indent=2) + "\n"


def render_float_vectors() -> str:
    return json.dumps(build_float_document(), ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    expected = render()
    expected_floats = render_float_vectors()
    if arguments.check:
        if not DESTINATION.exists() or DESTINATION.read_text(encoding="utf-8") != expected:
            parser.error("golden-vectors.json is stale; regenerate it")
        if (
            not FLOAT_DESTINATION.exists()
            or FLOAT_DESTINATION.read_text(encoding="utf-8") != expected_floats
        ):
            parser.error("float-vectors.json is stale; regenerate it")
        return
    DESTINATION.write_text(expected, encoding="utf-8", newline="\n")
    FLOAT_DESTINATION.write_text(expected_floats, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
