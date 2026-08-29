"""Run ModelOpt artifacts through TensorRT, Polygraphy, MCR gate, and bisect."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from m2riv.adapters import RecordedAdapter
from m2riv.bisect import BisectMode, BisectStatus, bisect_regression
from m2riv.core.identity import build_local_snapshot
from m2riv.core.models import EvidenceRef, ModelFamily, RuntimeProfile
from m2riv.engine import ObservationCache
from m2riv.evidence import (
    BackendCaseComparison,
    BackendComparisonEvidence,
    create_backend_comparison_evidence,
)
from m2riv.io import load_policy, load_suite
from m2riv.pipeline import ReleaseComparison, compare_exact_match
from m2riv.reports import verify_report_bundle, write_report_bundle

ROOT = Path(__file__).resolve().parents[2]
DATA_LOADER = Path(__file__).with_name("data_loader.py")
POLICY = Path(__file__).with_name("policy.yaml")
ABSOLUTE_TOLERANCE = 0.05
RELATIVE_TOLERANCE = 0.01
BUILD_SPECS = (
    ("build-00-pytorch-fp16", "build-00-pytorch-fp32.onnx", False, "fp16"),
    ("build-01-modelopt-int8-balanced", "build-01-modelopt-int8-balanced.onnx", True, "int8"),
    ("build-02-modelopt-int8-scale-065", "build-02-modelopt-int8-scale-065.onnx", True, "int8"),
    ("build-03-modelopt-int8-scale-060", "build-03-modelopt-int8-scale-060.onnx", True, "int8"),
)


def _preflight(polygraphy_command: str) -> dict[str, Any]:
    try:
        import polygraphy
        import tensorrt
    except ImportError as error:
        raise RuntimeError("TensorRT and Polygraphy are required for live GPU evidence") from error
    executable = shutil.which("nvidia-smi")
    if executable is None:
        raise RuntimeError("nvidia-smi is unavailable; GPU preflight is not evidence")
    completed = subprocess.run(  # noqa: S603
        [
            executable,
            "--query-gpu=name,driver_version,memory.total",
            "--format=csv,noheader,nounits",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise RuntimeError("nvidia-smi did not return a usable GPU cohort")
    gpu_name, driver, memory_mib = [
        item.strip() for item in completed.stdout.splitlines()[0].split(",")
    ]
    if shutil.which(polygraphy_command) is None and not Path(polygraphy_command).is_file():
        raise RuntimeError("the selected Polygraphy command is unavailable")
    return {
        "gpu_name": gpu_name,
        "driver_version": driver,
        "gpu_memory_mib": int(memory_mib),
        "tensorrt_version": tensorrt.__version__,
        "polygraphy_version": polygraphy.__version__,
        "operating_system": platform.platform(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
    }


def _sample_process_vram(process: subprocess.Popen[str]) -> float | None:
    try:
        import pynvml

        pynvml.nvmlInit()
        handles = [
            pynvml.nvmlDeviceGetHandleByIndex(index) for index in range(pynvml.nvmlDeviceGetCount())
        ]
    except Exception:
        process.wait()
        return None
    peak = 0
    try:
        while process.poll() is None:
            for handle in handles:
                try:
                    running = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
                except Exception:  # noqa: S112 - NVML support differs by driver mode.
                    continue
                for item in running:
                    if item.pid == process.pid and isinstance(item.usedGpuMemory, int):
                        peak = max(peak, item.usedGpuMemory)
            time.sleep(0.02)
    finally:
        pynvml.nvmlShutdown()
    return peak / (1024 * 1024) if peak else None


def _run_polygraphy(
    command: str,
    *,
    work: Path,
    onnx_name: str,
    build_name: str,
    int8: bool,
    cases: int,
    warmups: int,
) -> tuple[Path, Path, float | None, int]:
    engine = work / f"{build_name}.engine"
    results = work / f"{build_name}-polygraphy.json"
    arguments = [
        command,
        "run",
        onnx_name,
        "--onnxrt",
        "--trt",
        "--sequential-runners",
        "--fp16",
        "--data-loader-script",
        DATA_LOADER.name,
        "--warm-up",
        str(warmups),
        "--save-engine",
        engine.name,
        "--save-results",
        results.name,
        "--atol",
        str(ABSOLUTE_TOLERANCE),
        "--rtol",
        str(RELATIVE_TOLERANCE),
        "--silent",
    ]
    if int8:
        arguments.append("--int8")
    environment = os.environ.copy()
    environment["M2RIV_NVIDIA_SUITE"] = str(work / "suite.jsonl")
    environment["M2RIV_NVIDIA_CASES"] = str(cases)
    process = subprocess.Popen(  # noqa: S603
        arguments,
        cwd=work,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    peak_vram = _sample_process_vram(process)
    stdout, stderr = process.communicate()
    if process.returncode not in {0, 1} or not engine.is_file() or not results.is_file():
        detail = (stderr or stdout).strip()[-2000:]
        raise RuntimeError(f"Polygraphy execution failed for {build_name}: {detail}")
    return engine, results, peak_vram, int(process.returncode)


def _result_rows(
    results_path: Path,
    cases: tuple[Any, ...],
) -> tuple[list[dict[str, Any]], tuple[BackendCaseComparison, ...], str, str]:
    from polygraphy.comparator import RunResults

    results = RunResults.load(str(results_path))
    names = list(results.keys())
    onnx_name = next(name for name in names if name.startswith("onnxrt-runner"))
    trt_name = next(name for name in names if name.startswith("trt-runner"))
    onnx_rows = results[onnx_name]
    trt_rows = results[trt_name]
    if len(onnx_rows) != len(cases) or len(trt_rows) != len(cases):
        raise RuntimeError("Polygraphy did not return the declared case cohort")
    recorded: list[dict[str, Any]] = []
    comparisons: list[BackendCaseComparison] = []
    for case, onnx_row, trt_row in zip(cases, onnx_rows, trt_rows, strict=True):
        matches = {
            name: bool(
                np.allclose(
                    np.asarray(onnx_row[name]),
                    np.asarray(trt_row[name]),
                    atol=ABSOLUTE_TOLERANCE,
                    rtol=RELATIVE_TOLERANCE,
                )
            )
            for name in onnx_row
        }
        logits = np.asarray(trt_row["logits"])
        recorded.append(
            {
                "case_id": case.case_id,
                "output": int(np.argmax(logits)),
                "latency_ms": float(trt_row.runtime * 1000),
                "traces": {"polygraphy_output_matches": matches},
            }
        )
        comparisons.append(
            BackendCaseComparison(
                case_id=case.case_id,
                output_matches=matches,
                baseline_latency_ms=float(onnx_row.runtime * 1000),
                candidate_latency_ms=float(trt_row.runtime * 1000),
            )
        )
    return recorded, tuple(comparisons), onnx_name, trt_name


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


def _write_evidence(path: Path, evidence: BackendComparisonEvidence) -> None:
    path.write_text(evidence.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")


def _release_comparison(
    *,
    build_name: str,
    baseline_snapshot: Any,
    candidate_snapshot: Any,
    baseline_records: Path,
    candidate_records: Path,
    cases: tuple[Any, ...],
    baseline_evidence: BackendComparisonEvidence,
    candidate_evidence: BackendComparisonEvidence,
    destination: Path,
    profile: RuntimeProfile,
) -> ReleaseComparison:
    destination.mkdir(parents=True, exist_ok=True)
    evidence_items = {baseline_evidence.id: ("backend-comparison-baseline.json", baseline_evidence)}
    evidence_items.setdefault(
        candidate_evidence.id,
        ("backend-comparison-candidate.json", candidate_evidence),
    )
    references = tuple(
        EvidenceRef(id=identifier, kind="backend-comparison", uri=filename)
        for identifier, (filename, _) in evidence_items.items()
    )
    comparison = compare_exact_match(
        baseline=RecordedAdapter.from_jsonl(baseline_records, baseline_snapshot),
        candidate=RecordedAdapter.from_jsonl(candidate_records, candidate_snapshot),
        cases=cases,
        policy=load_policy(POLICY),
        cache=ObservationCache(destination / ".cache"),
        profile=profile,
        slice_keys=("risk",),
        baseline_adapter_fingerprint=f"polygraphy-tensorrt:{baseline_snapshot.id}",
        candidate_adapter_fingerprint=f"polygraphy-tensorrt:{candidate_snapshot.id}",
        additional_evidence=references,
        resamples=4_000,
    )
    write_report_bundle(
        comparison.report,
        destination,
        release_plan=comparison.plan,
        evidence_manifest=comparison.evidence_manifest,
    )
    for filename, evidence in evidence_items.values():
        _write_evidence(destination / filename, evidence)
    verify_report_bundle(destination, require_complete=True)
    return comparison


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--polygraphy-command", default="polygraphy")
    parser.add_argument("--cases", type=int, default=629)
    parser.add_argument("--warmups", type=int, default=10)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--allow-missing", action="store_true")
    arguments = parser.parse_args()
    try:
        receipt = _preflight(arguments.polygraphy_command)
        if arguments.preflight:
            print(json.dumps({"ready": True, **receipt}, indent=2))
            return
        if not 1 <= arguments.cases <= 10_000 or not 0 <= arguments.warmups <= 1_000:
            raise ValueError("cases or warmups are outside the bounded vertical limits")
        all_cases = load_suite(arguments.suite)
        cases = tuple(all_cases[: arguments.cases])
        if len(cases) != arguments.cases:
            raise ValueError("suite is smaller than the declared GPU cohort")
        arguments.output.mkdir(parents=True, exist_ok=True)
        artifact_output = arguments.output / "artifacts"
        result_output = arguments.output / "polygraphy"
        recorded_output = arguments.output / "recorded"
        report_output = arguments.output / "reports"
        for directory in (artifact_output, result_output, recorded_output, report_output):
            directory.mkdir(exist_ok=True)

        prepared: list[dict[str, Any]] = []
        with tempfile.TemporaryDirectory(prefix="m2riv-nvidia-") as temporary:
            work = Path(temporary)
            shutil.copy2(arguments.suite, work / "suite.jsonl")
            shutil.copy2(DATA_LOADER, work / DATA_LOADER.name)
            for build_name, onnx_name, int8, dtype in BUILD_SPECS:
                source = arguments.artifacts / onnx_name
                if not source.is_file():
                    raise ValueError(f"missing NVIDIA vertical artifact: {onnx_name}")
                shutil.copy2(source, work / onnx_name)
                engine, raw_results, peak_vram, polygraphy_exit = _run_polygraphy(
                    arguments.polygraphy_command,
                    work=work,
                    onnx_name=onnx_name,
                    build_name=build_name,
                    int8=int8,
                    cases=len(cases),
                    warmups=arguments.warmups,
                )
                onnx_target = artifact_output / onnx_name
                engine_target = artifact_output / engine.name
                raw_target = result_output / raw_results.name
                shutil.copy2(source, onnx_target)
                shutil.copy2(engine, engine_target)
                shutil.copy2(raw_results, raw_target)
                rows, backend_rows, onnx_runner, trt_runner = _result_rows(raw_target, cases)
                records = recorded_output / f"{build_name}.jsonl"
                _write_jsonl(records, rows)
                runtime = RuntimeProfile(
                    framework="TensorRT",
                    framework_version=receipt["tensorrt_version"],
                    device=receipt["gpu_name"],
                    dtype=dtype,
                    operating_system=receipt["operating_system"],
                    architecture=receipt["architecture"],
                    python_version=receipt["python_version"],
                    parameters={
                        "driver_version": receipt["driver_version"],
                        "polygraphy_version": receipt["polygraphy_version"],
                        "warmups": arguments.warmups,
                        "case_count": len(cases),
                    },
                )
                engine_snapshot = build_local_snapshot(
                    engine_target,
                    model_family=ModelFamily.CV,
                    runtime_profile=runtime,
                    execution_config={
                        "adapter": "polygraphy-tensorrt-results-v1",
                        "absolute_tolerance": ABSOLUTE_TOLERANCE,
                        "relative_tolerance": RELATIVE_TOLERANCE,
                    },
                    labels={"build": build_name},
                )
                onnx_snapshot = build_local_snapshot(
                    onnx_target,
                    model_family=ModelFamily.CV,
                    runtime_profile=RuntimeProfile(
                        framework="ONNX Runtime",
                        device="cpu",
                        dtype=dtype,
                        operating_system=receipt["operating_system"],
                        architecture=receipt["architecture"],
                        python_version=receipt["python_version"],
                    ),
                    execution_config={"adapter": "polygraphy-onnxrt-oracle-v1"},
                    labels={"build": build_name, "role": "oracle"},
                )
                backend_evidence = create_backend_comparison_evidence(
                    comparator_name="nvidia.polygraphy",
                    comparator_version=receipt["polygraphy_version"],
                    baseline_snapshot_id=onnx_snapshot.id,
                    candidate_snapshot_id=engine_snapshot.id,
                    absolute_tolerance=ABSOLUTE_TOLERANCE,
                    relative_tolerance=RELATIVE_TOLERANCE,
                    comparisons=backend_rows,
                    runtime_profile=runtime,
                    peak_vram_mib=peak_vram,
                    vram_measurement=(
                        "nvml-process-peak" if peak_vram is not None else "unavailable"
                    ),
                    limitations=(
                        "Polygraphy runtime is per single-case runner call after declared warmups.",
                        (
                            "NVML process peak was unavailable on this driver mode."
                            if peak_vram is None
                            else (
                                "NVML peak covers the Polygraphy process, including build "
                                "and runners."
                            )
                        ),
                    ),
                )
                prepared.append(
                    {
                        "name": build_name,
                        "records": records,
                        "snapshot": engine_snapshot,
                        "evidence": backend_evidence,
                        "runtime": runtime,
                        "onnx_runner": onnx_runner,
                        "trt_runner": trt_runner,
                        "polygraphy_exit": polygraphy_exit,
                    }
                )

        baseline = prepared[0]
        statuses: list[BisectStatus] = []
        summary: list[dict[str, Any]] = []
        for item in prepared:
            comparison = _release_comparison(
                build_name=item["name"],
                baseline_snapshot=baseline["snapshot"],
                candidate_snapshot=item["snapshot"],
                baseline_records=baseline["records"],
                candidate_records=item["records"],
                cases=cases,
                baseline_evidence=baseline["evidence"],
                candidate_evidence=item["evidence"],
                destination=report_output / item["name"],
                profile=item["runtime"],
            )
            status = BisectStatus(comparison.report.decision.status.value.lower())
            statuses.append(status)
            accuracy = next(
                metric for metric in comparison.report.metrics if metric.metric_id == "accuracy"
            )
            rare = next(
                metric
                for metric in comparison.report.metrics
                if metric.metric_id == "accuracy@risk=rare-high-ink"
            )
            latencies = [row.candidate_latency_ms or 0.0 for row in item["evidence"].comparisons]
            summary.append(
                {
                    "build": item["name"],
                    "overall_accuracy": accuracy.candidate_value,
                    "critical_slice_accuracy": rare.candidate_value,
                    "decision": comparison.report.decision.status.value,
                    "backend_matched_cases": item["evidence"].matched_case_count,
                    "case_count": len(cases),
                    "mean_latency_ms": statistics.mean(latencies),
                    "p95_latency_ms": sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)],
                    "peak_vram_mib": item["evidence"].peak_vram_mib,
                }
            )
        bisect = bisect_regression(
            len(statuses),
            lambda index: statuses[index],
            mode=BisectMode.MONOTONIC,
        )
        (arguments.output / "bisect-result.json").write_text(
            json.dumps(asdict(bisect), indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        final_receipt = {
            "schema_version": "1.0.0",
            "evidence_level": "live-target-gpu",
            "preflight": receipt,
            "case_count": len(cases),
            "warmups": arguments.warmups,
            "absolute_tolerance": ABSOLUTE_TOLERANCE,
            "relative_tolerance": RELATIVE_TOLERANCE,
            "builds": summary,
            "first_bad_index": bisect.first_failing_index,
            "first_bad_build": (
                summary[bisect.first_failing_index]["build"]
                if bisect.first_failing_index is not None
                else None
            ),
        }
        (arguments.output / "gpu-receipt.json").write_text(
            json.dumps(final_receipt, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        print(json.dumps(final_receipt, indent=2))
    except (OSError, RuntimeError, ValueError, StopIteration) as error:
        if arguments.preflight and arguments.allow_missing:
            print(json.dumps({"ready": False, "reason": str(error)}, indent=2))
            return
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(3) from error


if __name__ == "__main__":
    main()
