"""Fail-closed loaders for human-authored release inputs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode
from yaml.tokens import AliasToken

from m2riv.core.models import EvalCase
from m2riv.gate import GatePolicy
from m2riv.io.json import (
    MAX_JSON_DEPTH as MAX_JSON_DEPTH,
)
from m2riv.io.json import (
    MAX_JSON_NODES as MAX_JSON_NODES,
)
from m2riv.io.json import (
    StrictJSONError,
    parse_strict_json,
)


class InputFormatError(ValueError):
    """A suite or policy could not be safely interpreted."""


MAX_JSONL_LINE_BYTES = 1024 * 1024
MAX_JSONL_FILE_BYTES = 64 * 1024 * 1024
MAX_JSONL_RECORDS = 100_000
MAX_POLICY_BYTES = 1024 * 1024
MAX_YAML_ALIASES = 32
MAX_YAML_DEPTH = 64
MAX_YAML_NODES = 100_000


def _parse_jsonl_record(path: Path, line_number: int, raw_bytes: bytes) -> dict[str, Any] | None:
    try:
        raw_line = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise InputFormatError(f"{path}:{line_number}: input must be UTF-8") from error
    if not raw_line.strip():
        return None
    try:
        value = parse_strict_json(
            raw_line,
            max_depth=MAX_JSON_DEPTH,
            max_nodes=MAX_JSON_NODES,
        )
    except StrictJSONError as error:
        raise InputFormatError(f"{path}:{line_number}: invalid JSON: {error}") from error
    if not isinstance(value, dict):
        raise InputFormatError(f"{path}:{line_number}: row must be a JSON object")
    return value


def _load_jsonl(path: Path) -> tuple[tuple[int, dict[str, Any]], ...]:
    rows: list[tuple[int, dict[str, Any]]] = []
    try:
        if path.stat().st_size > MAX_JSONL_FILE_BYTES:
            raise InputFormatError(f"{path}: file exceeds {MAX_JSONL_FILE_BYTES} byte limit")
        with path.open("rb") as stream:
            line_number = 0
            total_bytes = 0
            while raw_bytes := stream.readline(MAX_JSONL_LINE_BYTES + 1):
                line_number += 1
                total_bytes += len(raw_bytes)
                if len(raw_bytes) > MAX_JSONL_LINE_BYTES:
                    raise InputFormatError(
                        f"{path}:{line_number}: line exceeds {MAX_JSONL_LINE_BYTES} byte limit"
                    )
                if total_bytes > MAX_JSONL_FILE_BYTES:
                    raise InputFormatError(
                        f"{path}: file exceeds {MAX_JSONL_FILE_BYTES} byte limit"
                    )
                record = _parse_jsonl_record(path, line_number, raw_bytes)
                if record is None:
                    continue
                rows.append((line_number, record))
                if len(rows) > MAX_JSONL_RECORDS:
                    raise InputFormatError(
                        f"{path}: record count exceeds {MAX_JSONL_RECORDS} limit"
                    )
    except OSError as error:
        raise InputFormatError(f"{path}: could not read input") from error
    if not rows:
        raise InputFormatError(f"{path}: file contains no records")
    return tuple(rows)


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """SafeLoader variant that refuses last-key-wins ambiguity."""

    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[Any, Any]:
        self.flatten_mapping(node)
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in seen
            except TypeError as error:
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found an unhashable mapping key",
                    key_node.start_mark,
                ) from error
            if duplicate:
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key {key!r}",
                    key_node.start_mark,
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def _validate_yaml_structure(value: Any) -> None:
    nodes = 0
    active: set[int] = set()

    def visit(node: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > MAX_YAML_NODES:
            raise InputFormatError(f"policy exceeds {MAX_YAML_NODES} node limit")
        if depth > MAX_YAML_DEPTH:
            raise InputFormatError(f"policy exceeds {MAX_YAML_DEPTH} depth limit")
        if not isinstance(node, (dict, list, tuple)):
            return
        identity = id(node)
        if identity in active:
            raise InputFormatError("policy contains a recursive YAML alias cycle")
        active.add(identity)
        try:
            values = node.items() if isinstance(node, dict) else enumerate(node)
            for key, child in values:
                if isinstance(node, dict):
                    visit(key, depth + 1)
                visit(child, depth + 1)
        finally:
            active.remove(identity)

    visit(value, 0)


def load_suite(path: str | Path) -> tuple[EvalCase, ...]:
    """Load a non-empty EvalCase JSONL suite with line-aware errors."""
    source = Path(path)
    cases: list[EvalCase] = []
    seen: set[str] = set()
    for line_number, row in _load_jsonl(source):
        try:
            case = EvalCase.model_validate(row)
        except ValidationError as error:
            raise InputFormatError(f"{source}:{line_number}: {error}") from error
        if case.case_id in seen:
            raise InputFormatError(f"{source}:{line_number}: duplicate case_id {case.case_id!r}")
        seen.add(case.case_id)
        cases.append(case)
    return tuple(cases)


def load_policy(path: str | Path) -> GatePolicy:
    """Load a strict GatePolicy from YAML without constructing arbitrary objects."""
    source = Path(path)
    try:
        payload = source.read_bytes()
        if len(payload) > MAX_POLICY_BYTES:
            raise InputFormatError(f"{source}: policy exceeds {MAX_POLICY_BYTES} byte limit")
        document = payload.decode("utf-8")
        alias_count = sum(isinstance(token, AliasToken) for token in yaml.scan(document))
        if alias_count > MAX_YAML_ALIASES:
            raise InputFormatError(f"{source}: YAML alias count exceeds {MAX_YAML_ALIASES} limit")
        # This loader derives from SafeLoader and only strengthens mapping-key checks.
        value = yaml.load(  # nosec B506
            document,
            Loader=_UniqueKeySafeLoader,  # noqa: S506
        )
        _validate_yaml_structure(value)
    except InputFormatError:
        raise
    except RecursionError as error:
        raise InputFormatError(f"{source}: invalid policy YAML: nesting limit exceeded") from error
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        raise InputFormatError(f"{source}: invalid policy YAML") from error
    if not isinstance(value, dict):
        raise InputFormatError(f"{source}: policy must be a YAML mapping")
    try:
        return GatePolicy.model_validate(value)
    except ValidationError as error:
        raise InputFormatError(f"{source}: {error}") from error
