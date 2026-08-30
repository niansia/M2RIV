"""Safe local config and suite loading."""

from merriv.io.loaders import (
    MAX_JSON_DEPTH,
    MAX_JSON_NODES,
    MAX_JSONL_FILE_BYTES,
    MAX_JSONL_LINE_BYTES,
    MAX_JSONL_RECORDS,
    MAX_POLICY_BYTES,
    MAX_YAML_ALIASES,
    MAX_YAML_DEPTH,
    MAX_YAML_NODES,
    InputFormatError,
    load_policy,
    load_suite,
)

__all__ = [
    "MAX_JSONL_FILE_BYTES",
    "MAX_JSONL_LINE_BYTES",
    "MAX_JSONL_RECORDS",
    "MAX_JSON_DEPTH",
    "MAX_JSON_NODES",
    "MAX_POLICY_BYTES",
    "MAX_YAML_ALIASES",
    "MAX_YAML_DEPTH",
    "MAX_YAML_NODES",
    "InputFormatError",
    "load_policy",
    "load_suite",
]
