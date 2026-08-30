"""Validate the bounded, source-linked model release regression corpus."""

from __future__ import annotations

import json
import re
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
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MCR_ID_PATTERN = re.compile(r"^mcr:sha256:[0-9a-f]{64}$")
TARGET_RECEIPT_REQUIRED = {
    "archive_name",
    "archive_sha256",
    "gpu_receipt_sha256",
    "source_commit",
    "target_evidence_id",
    "target_manifest_sha256",
    "verified_file_count",
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


def _validate_target_receipt(case: dict[str, Any], case_path: Path) -> None:
    receipt_value = case.get("target_receipt")
    if not isinstance(receipt_value, str):
        raise ValueError(f"{case_path.name} must name its target_receipt")
    receipt_path = _safe_relative(receipt_value)
    receipt = _load(receipt_path)
    if not isinstance(receipt, dict) or receipt.get("schema_version") != "1.1.0":
        raise ValueError(f"{receipt_path.name} is not a target receipt v1.1")
    missing = TARGET_RECEIPT_REQUIRED - set(receipt)
    if missing:
        raise ValueError(f"{receipt_path.name} is missing fields: {sorted(missing)}")
    for field in ("archive_sha256", "gpu_receipt_sha256", "target_manifest_sha256"):
        if not isinstance(receipt[field], str) or not SHA256_PATTERN.fullmatch(receipt[field]):
            raise ValueError(f"{receipt_path.name} has invalid {field}")
    if not isinstance(receipt["source_commit"], str) or not re.fullmatch(
        r"[0-9a-f]{40}", receipt["source_commit"]
    ):
        raise ValueError(f"{receipt_path.name} has invalid source_commit")
    if not isinstance(receipt["target_evidence_id"], str) or not MCR_ID_PATTERN.fullmatch(
        receipt["target_evidence_id"]
    ):
        raise ValueError(f"{receipt_path.name} has invalid target_evidence_id")
    archive_name = receipt["archive_name"]
    if not isinstance(archive_name, str) or PurePosixPath(archive_name).name != archive_name:
        raise ValueError(f"{receipt_path.name} has unsafe archive_name")
    if not isinstance(receipt["verified_file_count"], int) or receipt["verified_file_count"] < 1:
        raise ValueError(f"{receipt_path.name} has invalid verified_file_count")
    builds = receipt.get("builds")
    if not isinstance(builds, list) or len(builds) != 4:
        raise ValueError(f"{receipt_path.name} must contain four target builds")
    decisions = [item.get("decision") for item in builds if isinstance(item, dict)]
    if decisions != ["PASS", "PASS", "BLOCK", "BLOCK"]:
        raise ValueError(f"{receipt_path.name} has unexpected target release decisions")
    if receipt.get("first_bad_build") != case["expected_first_bad"]:
        raise ValueError(f"{receipt_path.name} has unexpected first bad build")
    case_counts = {item.get("case_count") for item in builds if isinstance(item, dict)}
    matches = {
        item.get("backend_matched_cases") for item in builds if isinstance(item, dict)
    }
    if case_counts != {629} or matches != {629}:
        raise ValueError(f"{receipt_path.name} does not retain 629/629 backend parity")
    if receipt_value not in case["source_paths"]:
        raise ValueError(f"{receipt_path.name} must be retained in source_paths")


def main() -> None:
    index = _load(CORPUS / "index.json")
    if index.get("schema_version") != "1.0.0" or not isinstance(index.get("cases"), list):
        raise ValueError("corpus index is invalid")
    seen: set[str] = set()
    counts = {"regression": 0, "negative-control": 0}
    status_counts = {
        "verified-in-ci": 0,
        "verified-on-target": 0,
        "historical-replay": 0,
    }
    for relative_case in index["cases"]:
        case_path = _safe_relative(f"corpus/{relative_case}")
        case = _load(case_path)
        missing = REQUIRED - set(case) if isinstance(case, dict) else REQUIRED
        if missing:
            raise ValueError(f"{case_path.name} is missing fields: {sorted(missing)}")
        if case["schema_version"] != "1.0.0" or case["status"] not in status_counts:
            raise ValueError(f"{case_path.name} is not a recognized v1 corpus case")
        if case["case_id"] in seen:
            raise ValueError(f"duplicate corpus case_id: {case['case_id']}")
        if case["kind"] not in counts or case["expected_decision"] not in {"PASS", "BLOCK"}:
            raise ValueError(f"{case_path.name} has invalid release semantics")
        for source in case["source_paths"]:
            if not _safe_relative(source).is_file():
                raise ValueError(f"missing corpus source path: {source}")
        if case["status"] == "verified-on-target":
            _validate_target_receipt(case, case_path)
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
