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
from m2riv.core.identity import build_local_snapshot, hash_artifact
from m2riv.core.models import ArtifactDigest, EvidenceRef, ModelFamily, RuntimeProfile
from m2riv.engine import ObservationCache
from m2riv.evidence import (
    BackendCaseComparison,
    FileDigestBinding,
    create_backend_comparison_evidence,
    create_build_provenance_evidence,
    create_snapshot_artifact_manifest,
    create_tool_native_evidence,
)
from m2riv.io import load_policy, load_suite
from m2riv.pipeline import ReleaseComparison, compare_exact_match
from m2riv.reports import verify_report_bundle, write_report_bundle
from m2riv.target import (
    create_target_evidence_manifest,
    verify_target_evidence_manifest,
    write_target_evidence_manifest,
)

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


def _git_commit() -> str:
    value = os.environ.get("GITHUB_SHA", "").strip().lower()
    if len(value) in {40, 64} and all(character in "0123456789abcdef" for character in value):
        return value
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required to bind target evidence to a source commit")
    completed = subprocess.run(  # noqa: S603 - resolved local Git executable, fixed argv.
        [git, "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    value = completed.stdout.strip().lower()
    if completed.returncode != 0 or len(value) not in {40, 64}:
        raise RuntimeError("an exact source commit is required for target evidence")
    return value


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
    environment["MERRIV_NVIDIA_SUITE"] = str(work / "suite.jsonl")
    environment["MERRIV_NVIDIA_CASES"] = str(cases)
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
    polygraphy_exit: int,
) -> tuple[list[dict[str, Any]], tuple[BackendCaseComparison, ...], str, str]:
    from polygraphy.comparator import Comparator, RunResults, SimpleCompareFunc
    from polygraphy.logger import G_LOGGER

    results = RunResults.load(str(results_path))
    names = list(results.keys())
    onnx_name = next(name for name in names if name.startswith("onnxrt-runner"))
    trt_name = next(name for name in names if name.startswith("trt-runner"))
    onnx_rows = results[onnx_name]
    trt_rows = results[trt_name]
    if len(onnx_rows) != len(cases) or len(trt_rows) != len(cases):
        raise RuntimeError("Polygraphy did not return the declared case cohort")
    selected = RunResults([(onnx_name, onnx_rows), (trt_name, trt_rows)])
    previous_severity = G_LOGGER.module_severity
    try:
        # The CLI already emitted the human-facing comparison. Re-evaluate the
        # retained native results quietly so the structured evidence is derived
        # from Polygraphy's own comparator instead of a hand-rolled NumPy check.
        G_LOGGER.module_severity = G_LOGGER.CRITICAL
        accuracy_results = Comparator.compare_accuracy(
            selected,
            compare_func=SimpleCompareFunc(
                atol=ABSOLUTE_TOLERANCE,
                rtol=RELATIVE_TOLERANCE,
            ),
        )
    finally:
        G_LOGGER.module_severity = previous_severity
    if len(accuracy_results) != 1:
        raise RuntimeError("Polygraphy returned an unexpected comparator result count")
    accuracy = accuracy_results[0]
    pair = (onnx_name, trt_name)
    if pair not in accuracy or len(accuracy[pair]) != len(cases):
        raise RuntimeError("Polygraphy comparator did not return the declared case cohort")
    recorded: list[dict[str, Any]] = []
    comparisons: list[BackendCaseComparison] = []
    for case, onnx_row, trt_row, output_results in zip(
        cases, onnx_rows, trt_rows, accuracy[pair], strict=True
    ):
        matches = {str(name): bool(result) for name, result in output_results.items()}
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
    all_matched = all(all(item.output_matches.values()) for item in comparisons)
    expected_exit = 0 if all_matched else 1
    if polygraphy_exit != expected_exit:
        raise RuntimeError(
            "Polygraphy CLI exit code disagrees with Comparator.compare_accuracy verdict"
        )
    return recorded, tuple(comparisons), onnx_name, trt_name


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


def _write_evidence(path: Path, evidence: Any) -> None:
    path.write_text(evidence.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")


def _release_comparison(
    *,
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    cases: tuple[Any, ...],
    destination: Path,
    profile: RuntimeProfile,
) -> ReleaseComparison:
    destination.mkdir(parents=True, exist_ok=True)
    evidence_items: dict[str, tuple[str, str, Any]] = {}
    retained_files: dict[str, Path] = {}
    for role, item in (("baseline", baseline), ("candidate", candidate)):
        native_filename = f"{role}-tool-native-evidence.json"
        raw_filename = f"{role}-polygraphy-run-results.json"
        native = item["native"].model_copy(
            update={
                "body": item["native"].body.model_copy(update={"uri": raw_filename})
            }
        )
        onnx_filename = f"{role}-onnx-artifact.onnx"
        engine_filename = f"{role}-tensorrt-engine.engine"
        onnx_manifest = item["onnx_manifest"].model_copy(
            update={
                "artifacts": tuple(
                    binding.model_copy(update={"uri": onnx_filename})
                    for binding in item["onnx_manifest"].artifacts
                )
            }
        )
        engine_manifest = item["engine_manifest"].model_copy(
            update={
                "artifacts": tuple(
                    binding.model_copy(update={"uri": engine_filename})
                    for binding in item["engine_manifest"].artifacts
                )
            }
        )
        descriptors = (
            ("backend-comparison", f"{role}-backend-comparison.json", item["evidence"]),
            ("tool-native-evidence", native_filename, native),
            ("snapshot-artifact-manifest", f"{role}-onnx-snapshot.json", onnx_manifest),
            ("snapshot-artifact-manifest", f"{role}-engine-snapshot.json", engine_manifest),
            ("build-provenance", f"{role}-artifact-build.json", item["artifact_build"]),
            ("build-provenance", f"{role}-tensorrt-build.json", item["tensorrt_build"]),
        )
        for kind, filename, evidence in descriptors:
            evidence_items.setdefault(evidence.id, (kind, filename, evidence))
        retained_files.setdefault(raw_filename, item["raw_results"])
        retained_files.setdefault(onnx_filename, item["onnx_path"])
        retained_files.setdefault(engine_filename, item["engine_path"])
    references = tuple(
        EvidenceRef(id=identifier, kind=kind, uri=filename)
        for identifier, (kind, filename, _) in evidence_items.items()
    )
    comparison = compare_exact_match(
        baseline=RecordedAdapter.from_jsonl(baseline["records"], baseline["snapshot"]),
        candidate=RecordedAdapter.from_jsonl(candidate["records"], candidate["snapshot"]),
        cases=cases,
        policy=load_policy(POLICY),
        cache=ObservationCache(destination / ".cache"),
        profile=profile,
        slice_keys=("risk",),
        baseline_adapter_fingerprint=f"polygraphy-tensorrt:{baseline['snapshot'].id}",
        candidate_adapter_fingerprint=f"polygraphy-tensorrt:{candidate['snapshot'].id}",
        additional_evidence=references,
        resamples=4_000,
    )
    write_report_bundle(
        comparison.report,
        destination,
        release_plan=comparison.plan,
        evidence_manifest=comparison.evidence_manifest,
    )
    for _, filename, evidence in evidence_items.values():
        _write_evidence(destination / filename, evidence)
    for filename, source in retained_files.items():
        shutil.copy2(source, destination / filename)
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

        build_input_path = arguments.artifacts / "artifact-build-input.json"
        if not build_input_path.is_file():
            raise ValueError("artifact builder did not retain artifact-build-input.json")
        build_input = json.loads(build_input_path.read_text(encoding="utf-8"))
        if build_input.get("schema_version") != "0.1.0":
            raise ValueError("artifact build input uses an unsupported schema")
        build_inputs = {item["build_name"]: item for item in build_input["builds"]}
        if set(build_inputs) != {item[0] for item in BUILD_SPECS}:
            raise ValueError("artifact build input does not cover the declared build sequence")
        source_commit = _git_commit()
        if build_input.get("source_commit") not in {None, source_commit}:
            raise ValueError("artifact build input was produced from a different source commit")
        fixture_artifact = ArtifactDigest(
            digest=build_input["source_fixture_sha256"],
            size_bytes=build_input["source_fixture_size_bytes"],
            logical_name="digits-mlp-fp32.onnx",
        )
        source_model_digest = hash_artifact(
            arguments.artifacts / "build-00-pytorch-fp32.onnx"
        )
        shutil.copy2(build_input_path, arguments.output / "artifact-build-input.json")
        shutil.copy2(arguments.suite, arguments.output / "suite.jsonl")
        shutil.copy2(POLICY, arguments.output / "policy.yaml")

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
                rows, backend_rows, onnx_runner, trt_runner = _result_rows(
                    raw_target, cases, polygraphy_exit
                )
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
                native_evidence = create_tool_native_evidence(
                    raw_target,
                    uri="polygraphy-run-results.json",
                    producer_name="nvidia.polygraphy",
                    producer_version=receipt["polygraphy_version"],
                    media_type="application/vnd.nvidia.polygraphy.run-results+json",
                    purpose="ONNX Runtime and TensorRT comparator-native parity evidence",
                    exit_code=polygraphy_exit,
                    runner_names=(onnx_runner, trt_runner),
                )
                backend_evidence = create_backend_comparison_evidence(
                    comparator_name="nvidia.polygraphy",
                    comparator_version=receipt["polygraphy_version"],
                    comparator_exit_code=polygraphy_exit,
                    baseline_runner=onnx_runner,
                    candidate_runner=trt_runner,
                    tool_native_evidence_id=native_evidence.id,
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
                onnx_digest = hash_artifact(onnx_target)
                engine_digest = hash_artifact(engine_target)
                onnx_manifest = create_snapshot_artifact_manifest(
                    onnx_snapshot,
                    (
                        FileDigestBinding(
                            uri=onnx_target.name,
                            sha256=onnx_digest.digest,
                            size_bytes=onnx_digest.size_bytes,
                            logical_name=onnx_digest.logical_name or onnx_target.name,
                        ),
                    ),
                )
                engine_manifest = create_snapshot_artifact_manifest(
                    engine_snapshot,
                    (
                        FileDigestBinding(
                            uri=engine_target.name,
                            sha256=engine_digest.digest,
                            size_bytes=engine_digest.size_bytes,
                            logical_name=engine_digest.logical_name or engine_target.name,
                        ),
                    ),
                )
                build_definition = build_inputs[build_name]
                if build_definition["artifact_sha256"] != onnx_digest.digest:
                    raise RuntimeError(
                        "retained ONNX artifact differs from its build input manifest"
                    )
                artifact_build = create_build_provenance_evidence(
                    build_name=build_name,
                    builder_name=build_definition["builder"],
                    builder_version=build_definition["builder_version"],
                    source_commit=source_commit,
                    input_artifacts=(
                        (
                            fixture_artifact
                            if build_name.startswith("build-00")
                            else source_model_digest
                        ),
                    ),
                    output_artifacts=(onnx_digest,),
                    output_snapshot_id=onnx_snapshot.id,
                    parameters={
                        **build_definition["parameters"],
                        "build_environment_versions": build_input["versions"],
                    },
                    calibration_cohort_digest=(
                        build_input["calibration_cohort_sha256"]
                        if build_definition["builder"] == "nvidia-modelopt"
                        else None
                    ),
                )
                tensorrt_build = create_build_provenance_evidence(
                    build_name=f"{build_name}-tensorrt",
                    builder_name="nvidia-tensorrt",
                    builder_version=receipt["tensorrt_version"],
                    source_commit=source_commit,
                    input_artifacts=(onnx_digest,),
                    output_artifacts=(engine_digest,),
                    output_snapshot_id=engine_snapshot.id,
                    parent_build_id=artifact_build.id,
                    parameters={
                        "fp16": True,
                        "int8": int8,
                        "warmups": arguments.warmups,
                        "case_count": len(cases),
                        "absolute_tolerance": ABSOLUTE_TOLERANCE,
                        "relative_tolerance": RELATIVE_TOLERANCE,
                    },
                    limitations=(
                        (
                            "TensorRT tactic selection is target-specific and the engine is "
                            "not portable."
                        ),
                    ),
                )
                prepared.append(
                    {
                        "name": build_name,
                        "records": records,
                        "snapshot": engine_snapshot,
                        "evidence": backend_evidence,
                        "native": native_evidence,
                        "onnx_manifest": onnx_manifest,
                        "engine_manifest": engine_manifest,
                        "artifact_build": artifact_build,
                        "tensorrt_build": tensorrt_build,
                        "onnx_path": onnx_target,
                        "engine_path": engine_target,
                        "raw_results": raw_target,
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
                baseline=baseline,
                candidate=item,
                cases=cases,
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
        gpu_receipt_path = arguments.output / "gpu-receipt.json"
        gpu_receipt_path.write_text(
            json.dumps(final_receipt, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        target_profile = RuntimeProfile(
            framework="TensorRT",
            framework_version=receipt["tensorrt_version"],
            device=receipt["gpu_name"],
            operating_system=receipt["operating_system"],
            architecture=receipt["architecture"],
            python_version=receipt["python_version"],
            parameters={
                "driver_version": receipt["driver_version"],
                "gpu_memory_mib": receipt["gpu_memory_mib"],
            },
        )
        target_manifest = create_target_evidence_manifest(
            root=arguments.output,
            source_commit=source_commit,
            target_profile=target_profile,
            tool_versions={
                "polygraphy": receipt["polygraphy_version"],
                "tensorrt": receipt["tensorrt_version"],
                **build_input["versions"],
            },
            report_builds=tuple(
                (item["name"], f"reports/{item['name']}") for item in prepared
            ),
            first_bad_build=final_receipt["first_bad_build"],
        )
        write_target_evidence_manifest(
            target_manifest, arguments.output / "target-evidence-manifest.json"
        )
        target_verification = verify_target_evidence_manifest(arguments.output)
        print(
            json.dumps(
                {
                    **final_receipt,
                    "target_evidence_id": target_verification.target_evidence_id,
                    "verified_file_count": target_verification.verified_file_count,
                },
                indent=2,
            )
        )
    except (OSError, RuntimeError, ValueError, StopIteration) as error:
        if arguments.preflight and arguments.allow_missing:
            print(json.dumps({"ready": False, "reason": str(error)}, indent=2))
            return
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(3) from error


if __name__ == "__main__":
    main()
