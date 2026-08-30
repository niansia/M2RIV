"""Translate Polygraphy comparison results into a Model Change Report bundle."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

MAX_RESULTS_BYTES = 64 * 1024 * 1024


def _load_normalized(path: Path) -> dict[str, Any]:
    if path.stat().st_size > MAX_RESULTS_BYTES:
        raise ValueError("normalized Polygraphy results exceed the size limit")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0.0":
        raise ValueError("normalized Polygraphy results must use schema_version 1.0.0")
    iterations = payload.get("iterations")
    if not isinstance(iterations, list) or not 1 <= len(iterations) <= 100_000:
        raise ValueError("normalized Polygraphy results require 1..100000 iterations")
    seen: set[str] = set()
    for iteration in iterations:
        if not isinstance(iteration, dict):
            raise ValueError("each normalized Polygraphy iteration must be an object")
        case_id = iteration.get("case_id")
        outputs = iteration.get("outputs")
        if not isinstance(case_id, str) or not case_id or len(case_id) > 256 or case_id in seen:
            raise ValueError("Polygraphy case IDs must be unique strings of at most 256 chars")
        if not isinstance(outputs, dict) or not outputs:
            raise ValueError("each Polygraphy iteration must include output match results")
        if any(
            not isinstance(name, str) or not isinstance(value, bool)
            for name, value in outputs.items()
        ):
            raise ValueError("Polygraphy output match results must map names to booleans")
        seen.add(case_id)
    return payload


def _from_polygraphy(
    path: Path,
    *,
    baseline_runner: str,
    candidate_runner: str,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> dict[str, Any]:
    try:
        from polygraphy.comparator import Comparator, RunResults, SimpleCompareFunc
    except ImportError as error:
        raise RuntimeError("Polygraphy is required for --polygraphy-results") from error

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
    normalized = []
    for index, output_results in enumerate(comparisons[pair]):
        normalized.append(
            {
                "case_id": f"polygraphy-{index:06d}",
                "outputs": {str(name): bool(value) for name, value in output_results.items()},
            }
        )
    return {
        "schema_version": "1.0.0",
        "baseline_runner": baseline_runner,
        "candidate_runner": candidate_runner,
        "iterations": normalized,
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


def produce_inputs(payload: dict[str, Any], destination: Path) -> tuple[Path, Path, Path]:
    """Write Merriv's public recorded-output boundary from normalized results."""
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
            {"case_id": case_id, "output": "match", "traces": {"source": "baseline"}}
        )
        candidate_rows.append(
            {
                "case_id": case_id,
                "output": "match" if matched else "mismatch",
                "traces": {"polygraphy_output_matches": outputs},
            }
        )
    suite = destination / "suite.jsonl"
    baseline = destination / "baseline.jsonl"
    candidate = destination / "candidate.jsonl"
    _write_jsonl(suite, suite_rows)
    _write_jsonl(baseline, baseline_rows)
    _write_jsonl(candidate, candidate_rows)
    return baseline, candidate, suite


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--polygraphy-results", type=Path)
    source.add_argument("--normalized-results", type=Path)
    parser.add_argument("--baseline-runner", default="onnxrt-runner")
    parser.add_argument("--candidate-runner", default="trt-runner")
    parser.add_argument("--absolute-tolerance", type=float, default=1e-5)
    parser.add_argument("--relative-tolerance", type=float, default=1e-5)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--merriv-command",
        "--m2riv-command",
        dest="merriv_command",
        default="merriv",
    )
    parser.add_argument("--translate-only", action="store_true")
    arguments = parser.parse_args()

    try:
        if arguments.normalized_results is not None:
            payload = _load_normalized(arguments.normalized_results)
        else:
            payload = _from_polygraphy(
                arguments.polygraphy_results,
                baseline_runner=arguments.baseline_runner,
                candidate_runner=arguments.candidate_runner,
                absolute_tolerance=arguments.absolute_tolerance,
                relative_tolerance=arguments.relative_tolerance,
            )
        baseline, candidate, suite = produce_inputs(payload, arguments.output / "translated")
        if arguments.translate_only:
            print(arguments.output / "translated")
            return
        command = [
            arguments.merriv_command,
            "compare",
            str(baseline),
            str(candidate),
            "--suite",
            str(suite),
            "--policy",
            str(arguments.policy),
            "--output",
            str(arguments.output / "mcr"),
        ]
        # Executing the explicitly selected local Merriv reference binary is the
        # integration boundary; arguments remain an argv list, never a shell.
        completed = subprocess.run(command, check=False)  # noqa: S603
        raise SystemExit(completed.returncode)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(3) from error


if __name__ == "__main__":
    main()
