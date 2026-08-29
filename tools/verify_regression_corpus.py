"""Validate the bounded, source-linked model release regression corpus."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "corpus"
MAX_CASE_BYTES = 64 * 1024
REQUIRED = {
    "schema_version",
    "case_id",
    "title",
    "kind",
    "axis",
    "status",
    "expected_decision",
    "expected_first_bad",
    "reproduction",
    "verification",
    "source_paths",
    "limitations",
}


def _load(path: Path) -> Any:
    if path.stat().st_size > MAX_CASE_BYTES:
        raise ValueError(f"corpus document exceeds size limit: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_relative(value: str) -> Path:
    relative = PurePosixPath(value.replace("\\", "/"))
    invalid_part = any(part in {"", ".", ".."} for part in relative.parts)
    if relative.is_absolute() or not relative.parts or invalid_part:
        raise ValueError(f"unsafe corpus path: {value}")
    return ROOT.joinpath(*relative.parts)


def main() -> None:
    index = _load(CORPUS / "index.json")
    if index.get("schema_version") != "1.0.0" or not isinstance(index.get("cases"), list):
        raise ValueError("corpus index is invalid")
    seen: set[str] = set()
    counts = {"regression": 0, "negative-control": 0}
    status_counts = {"verified-in-ci": 0, "verified-on-target": 0}
    for relative_case in index["cases"]:
        case_path = _safe_relative(f"corpus/{relative_case}")
        case = _load(case_path)
        missing = REQUIRED - set(case) if isinstance(case, dict) else REQUIRED
        if missing:
            raise ValueError(f"{case_path.name} is missing fields: {sorted(missing)}")
        if case["schema_version"] != "1.0.0" or case["status"] not in status_counts:
            raise ValueError(f"{case_path.name} is not a verified v1 corpus case")
        if case["case_id"] in seen:
            raise ValueError(f"duplicate corpus case_id: {case['case_id']}")
        if case["kind"] not in counts or case["expected_decision"] not in {"PASS", "BLOCK"}:
            raise ValueError(f"{case_path.name} has invalid release semantics")
        for source in case["source_paths"]:
            if not _safe_relative(source).is_file():
                raise ValueError(f"missing corpus source path: {source}")
        seen.add(case["case_id"])
        counts[case["kind"]] += 1
        status_counts[case["status"]] += 1
    print(
        json.dumps(
            {"valid": True, "case_count": len(seen), **counts, **status_counts},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
