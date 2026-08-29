"""Bounded, ambiguity-free JSON parsing for untrusted evidence."""

from __future__ import annotations

import json
from typing import Any

MAX_JSON_DEPTH = 64
MAX_JSON_NODES = 100_000


class StrictJSONError(ValueError):
    """JSON was malformed, ambiguous, non-finite, or outside its resource budget."""


class _DuplicateKeyError(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant {value!r} is not allowed")


def _validate_structure(value: Any, *, max_depth: int, max_nodes: int) -> None:
    def validate_text(text: str) -> None:
        try:
            text.encode("utf-8")
        except UnicodeEncodeError as error:
            raise StrictJSONError("JSON contains an invalid Unicode scalar") from error

    nodes = 0
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        node, depth = stack.pop()
        nodes += 1
        if nodes > max_nodes:
            raise StrictJSONError(f"JSON exceeds {max_nodes} node limit")
        if depth > max_depth:
            raise StrictJSONError(f"JSON exceeds {max_depth} depth limit")
        if isinstance(node, dict):
            for key in node:
                validate_text(key)
            stack.extend((child, depth + 1) for child in node.values())
        elif isinstance(node, list):
            stack.extend((child, depth + 1) for child in node)
        elif isinstance(node, str):
            validate_text(node)


def parse_strict_json(
    document: str | bytes,
    *,
    max_depth: int = MAX_JSON_DEPTH,
    max_nodes: int = MAX_JSON_NODES,
) -> Any:
    """Parse UTF-8 JSON while rejecting duplicate keys and parser exhaustion."""
    if isinstance(document, bytes):
        try:
            document = document.decode("utf-8")
        except UnicodeDecodeError as error:
            raise StrictJSONError("input must be UTF-8") from error
    try:
        value = json.loads(
            document,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except RecursionError as error:
        raise StrictJSONError("JSON nesting limit exceeded during parsing") from error
    except json.JSONDecodeError as error:
        raise StrictJSONError(error.msg) from error
    except (_DuplicateKeyError, ValueError) as error:
        raise StrictJSONError(str(error)) from error
    _validate_structure(value, max_depth=max_depth, max_nodes=max_nodes)
    return value
