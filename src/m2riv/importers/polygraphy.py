"""Translate Polygraphy runner comparisons into the recorded-output boundary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from m2riv.core.identity import read_verified_file
from m2riv.io.json import StrictJSONError, parse_strict_json

MAX_POLYGRAPHY_RESULTS_BYTES = 64 * 1024 * 1024
MAX_POLYGRAPHY_ITERATIONS = 100_000
MAX_OUTPUTS_PER_ITERATION = 1_024


def _validate_normalized(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0.0":
        raise ValueError("normalized Polygraphy results must use schema_version 1.0.0")
    iterations = payload.get("iterations")
    if not isinstance(iterations, list) or not 1 <= len(iterations) <= MAX_POLYGRAPHY_ITERATIONS:
        raise ValueError("normalized Polygraphy results require 1..100000 iterations")
    for runner_field in ("baseline_runner", "candidate_runner"):
        runner = payload.get(runner_field)
        if not isinstance(runner, str) or not 1 <= len(runner) <= 256:
            raise ValueError(f"{runner_field} must be a non-empty string of at most 256 chars")
    seen: set[str] = set()
    for iteration in iterations:
        if not isinstance(iteration, dict):
            raise ValueError("each normalized Polygraphy iteration must be an object")
        case_id = iteration.get("case_id")
        outputs = iteration.get("outputs")
        if (
            not isinstance(case_id, str)
            or not case_id
            or len(case_id) > 256
            or case_id in seen
        ):
            raise ValueError("Polygraphy case IDs must be unique strings of at most 256 chars")
        if (
            not isinstance(outputs, dict)
            or not outputs
            or len(outputs) > MAX_OUTPUTS_PER_ITERATION
        ):
            raise ValueError("each Polygraphy iteration must include 1..1024 output results")
        if any(
            not isinstance(name, str)
            or not 1 <= len(name) <= 256
            or not isinstance(value, bool)
            for name, value in outputs.items()
        ):
            raise ValueError(
                "Polygraphy output results must map bounded non-empty names to booleans"
            )
        seen.add(case_id)
    return payload


def load_normalized_polygraphy(path: Path) -> dict[str, Any]:
    """Load the small documented JSON interchange without importing Polygraphy."""

    try:
        payload = parse_strict_json(
            read_verified_file(path, max_bytes=MAX_POLYGRAPHY_RESULTS_BYTES)
        )
    except StrictJSONError as error:
        raise ValueError(f"invalid normalized Polygraphy JSON: {error}") from error
    return _validate_normalized(payload)


def normalize_polygraphy_results(
    path: Path,
    *,
    baseline_runner: str,
    candidate_runner: str,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> dict[str, Any]:
    """Use Polygraphy's native APIs to compare two retained runner results."""

    try:
        from polygraphy.comparator import (  # type: ignore[import-not-found]
            Comparator,
            RunResults,
            SimpleCompareFunc,
        )
    except ImportError as error:
        raise RuntimeError(
            "Polygraphy is required for native results; install it or use --format normalized"
        ) from error

    if path.stat().st_size > MAX_POLYGRAPHY_RESULTS_BYTES:
        raise ValueError("Polygraphy results exceed the 64 MiB importer limit")
    results = RunResults.load(str(path))
    available = set(results.keys())
    if baseline_runner not in available or candidate_runner not in available:
        raise ValueError(f"requested runners are unavailable; found: {sorted(available)}")
    selected = RunResults(
        [
            (baseline_runner, results[baseline_runner]),
            (candidate_runner, results[candidate_runner]),
        ]
    )
    comparison_results = Comparator.compare_accuracy(
        selected,
        compare_func=SimpleCompareFunc(atol=absolute_tolerance, rtol=relative_tolerance),
    )
    if len(comparison_results) != 1:
        raise ValueError("Polygraphy returned an unexpected comparator result count")
    comparisons = comparison_results[0]
    pair = (baseline_runner, candidate_runner)
    if pair not in comparisons:
        raise ValueError("Polygraphy did not produce the requested runner-pair comparison")
    normalized = [
        {
            "case_id": f"polygraphy-{index:06d}",
            "outputs": {str(name): bool(value) for name, value in output_results.items()},
        }
        for index, output_results in enumerate(comparisons[pair])
    ]
    return _validate_normalized(
        {
            "schema_version": "1.0.0",
            "baseline_runner": baseline_runner,
            "candidate_runner": candidate_runner,
            "iterations": normalized,
        }
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows
        ),
        encoding="utf-8",
        newline="\n",
    )


def write_recorded_inputs(
    payload: dict[str, Any], destination: Path
) -> tuple[Path, Path, Path]:
    """Write the language-neutral recorded JSONL boundary used by ``merriv compare``."""

    payload = _validate_normalized(payload)
    destination.mkdir(parents=True, exist_ok=True)
    suite_rows: list[dict[str, Any]] = []
    baseline_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    for iteration in payload["iterations"]:
        case_id = iteration["case_id"]
        outputs = iteration["outputs"]
        matched = all(outputs.values())
        suite_rows.append(
            {
                "case_id": case_id,
                "input": {"polygraphy_iteration": case_id},
                "expected": "match",
            }
        )
        baseline_rows.append(
            {
                "case_id": case_id,
                "output": "match",
                "traces": {"runner": payload["baseline_runner"]},
            }
        )
        candidate_rows.append(
            {
                "case_id": case_id,
                "output": "match" if matched else "mismatch",
                "traces": {
                    "runner": payload["candidate_runner"],
                    "polygraphy_output_matches": outputs,
                },
            }
        )
    suite = destination / "suite.jsonl"
    baseline = destination / "baseline.jsonl"
    candidate = destination / "candidate.jsonl"
    _write_jsonl(suite, suite_rows)
    _write_jsonl(baseline, baseline_rows)
    _write_jsonl(candidate, candidate_rows)
    return baseline, candidate, suite
