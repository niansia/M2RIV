"""Materialize language-neutral typed values used by identity conformance vectors."""

from __future__ import annotations

import struct
from datetime import datetime
from pathlib import Path
from typing import Any


def materialize_typed_value(value: Any) -> Any:
    """Decode the conformance-only typed-value notation into Python values."""
    if isinstance(value, list):
        return [materialize_typed_value(item) for item in value]
    if not isinstance(value, dict):
        return value

    if len(value) == 1 and "$float64" in value:
        bits = value["$float64"]
        if not isinstance(bits, str) or len(bits) != 16:
            raise ValueError("$float64 must contain exactly 16 hexadecimal digits")
        return struct.unpack(">d", bytes.fromhex(bits))[0]
    if len(value) == 1 and "$integer" in value:
        integer = value["$integer"]
        if not isinstance(integer, str):
            raise TypeError("$integer must contain a base-10 string")
        return int(integer)
    if len(value) == 1 and "$datetime" in value:
        timestamp = value["$datetime"]
        if not isinstance(timestamp, str):
            raise TypeError("$datetime must contain an RFC 3339 string")
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("$datetime must be timezone-aware")
        return parsed
    if len(value) == 1 and "$path" in value:
        path = value["$path"]
        if not isinstance(path, str):
            raise TypeError("$path must contain a string")
        return Path(path.replace("\\", "/"))
    if len(value) == 1 and "$set" in value:
        members = value["$set"]
        if not isinstance(members, list) or not all(isinstance(item, str) for item in members):
            raise TypeError("$set must contain only strings in the portable v1 profile")
        return frozenset(members)

    return {key: materialize_typed_value(item) for key, item in value.items()}
