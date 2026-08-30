"""Bounded, CPU-only per-tensor numerical diff for self-contained ONNX graphs."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from m2riv.artifacts.inspector import ArtifactInspectionError, inspect_artifact
from m2riv.artifacts.models import NumericalDiff, TensorNumericalDiff
from m2riv.core.identity import fingerprint, read_verified_file
from m2riv.core.models import EvalCase

MAX_NUMERICAL_CASES = 128
MAX_NUMERICAL_TENSORS = 4096
MAX_ELEMENTS_PER_TENSOR = 4_000_000
MAX_TOTAL_ELEMENTS = 32_000_000


class NumericalDiffError(ValueError):
    """The numerical comparison could not run inside its resource boundary."""


@dataclass(slots=True)
class _Accumulator:
    count: int = 0
    abs_sum: float = 0.0
    sq_sum: float = 0.0
    max_abs: float = 0.0
    max_rel: float = 0.0
    dot: float = 0.0
    baseline_sq: float = 0.0
    candidate_sq: float = 0.0
    within: bool = True
    shape: tuple[int, ...] | None = None
    shape_changed: bool = False
    baseline_dtype: str = ""
    candidate_dtype: str = ""


@dataclass(frozen=True, slots=True)
class _LoadedGraphs:
    baseline_profile: Any
    candidate_profile: Any
    baseline_model: Any
    candidate_model: Any
    baseline_values: dict[str, Any]
    candidate_values: dict[str, Any]
    common_names: frozenset[str]
    tensor_names: tuple[str, ...]


def _load_model(path: Path) -> tuple[Any, Any]:
    profile = inspect_artifact(path)
    if profile.onnx is None:
        raise NumericalDiffError("numerical diff requires one inspectable ONNX model per side")
    if profile.onnx.uses_external_data:
        raise NumericalDiffError("numerical diff refuses external ONNX tensor data")
    components = tuple(item for item in profile.components if item.role == "model-onnx")
    if len(components) != 1:
        raise NumericalDiffError("numerical diff requires exactly one ONNX component")
    model_path = path if path.is_file() else path / components[0].relative_path
    try:
        import onnx

        encoded = read_verified_file(
            model_path,
            max_bytes=components[0].size_bytes,
            expected_digest=components[0].digest,
        )
        model = onnx.load_model_from_string(encoded)
        inferred = onnx.shape_inference.infer_shapes(model)
    except ImportError as error:
        raise NumericalDiffError("numerical diff requires the optional 'onnx' extra") from error
    except ValueError as error:
        raise NumericalDiffError(str(error)) from error
    except Exception:
        raise NumericalDiffError("ONNX shape inference failed") from None
    return profile, inferred


def _typed_values(model: Any) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for value in (*model.graph.value_info, *model.graph.output):
        if value.name and value.type.HasField("tensor_type") and value.type.tensor_type.elem_type:
            values.setdefault(value.name, value)
    return values


def _ordered_outputs(model: Any, available: Set[str]) -> tuple[str, ...]:
    ordered: list[str] = []
    for node in model.graph.node:
        for name in node.output:
            if name in available and name not in ordered:
                ordered.append(name)
    for output in model.graph.output:
        if output.name in available and output.name not in ordered:
            ordered.append(output.name)
    return tuple(ordered)


def _produced_names(model: Any) -> set[str]:
    return {name for node in model.graph.node for name in node.output if name} | {
        output.name for output in model.graph.output if output.name
    }


def _instrument(model: Any, names: Sequence[str]) -> bytes:
    typed = _typed_values(model)
    existing = {item.name for item in model.graph.output}
    for name in names:
        if name not in existing:
            model.graph.output.add().CopyFrom(typed[name])
    return bytes(model.SerializeToString())


def _numpy_dtypes(np: Any) -> dict[str, Any]:
    return {
        "tensor(float)": np.float32,
        "tensor(float16)": np.float16,
        "tensor(double)": np.float64,
        "tensor(int64)": np.int64,
        "tensor(int32)": np.int32,
        "tensor(int16)": np.int16,
        "tensor(int8)": np.int8,
        "tensor(uint8)": np.uint8,
        "tensor(bool)": np.bool_,
    }


def _feeds(case: EvalCase, inputs: Sequence[Any], np: Any) -> dict[str, Any]:
    names = {item.name for item in inputs}
    values = case.input if isinstance(case.input, dict) else None
    if values is None:
        if len(inputs) != 1:
            raise NumericalDiffError("multi-input models require a complete input mapping")
        values = {inputs[0].name: case.input}
    if set(values) != names:
        raise NumericalDiffError("case input mapping does not match ONNX graph inputs")
    dtypes = _numpy_dtypes(np)
    result: dict[str, Any] = {}
    total_elements = 0
    for metadata in inputs:
        dtype = dtypes.get(metadata.type)
        if dtype is None:
            raise NumericalDiffError(f"unsupported ONNX input type: {metadata.type}")
        try:
            array = np.asarray(values[metadata.name], dtype=dtype)
        except Exception:
            raise NumericalDiffError(
                "case input could not be converted to its ONNX dtype"
            ) from None
        expected_rank = len(metadata.shape)
        if array.ndim == expected_rank - 1:
            array = np.expand_dims(array, axis=0)
        if array.ndim != expected_rank:
            raise NumericalDiffError("case input rank does not match the ONNX graph")
        total_elements += int(array.size)
        if array.size > MAX_ELEMENTS_PER_TENSOR or total_elements > MAX_TOTAL_ELEMENTS:
            raise NumericalDiffError("case input exceeds the numerical diff element budget")
        result[metadata.name] = array
    return result


def _validate_request(
    cases: Sequence[EvalCase], absolute_tolerance: float, relative_tolerance: float
) -> None:
    if not cases or len(cases) > MAX_NUMERICAL_CASES:
        raise ValueError(f"numerical diff requires 1 to {MAX_NUMERICAL_CASES} cases")
    if (
        not math.isfinite(absolute_tolerance)
        or not math.isfinite(relative_tolerance)
        or absolute_tolerance < 0
        or relative_tolerance < 0
    ):
        raise ValueError("numerical diff tolerances must be finite and non-negative")


def _load_graphs(baseline: str | Path, candidate: str | Path) -> _LoadedGraphs:
    try:
        baseline_profile, baseline_model = _load_model(Path(baseline))
        candidate_profile, candidate_model = _load_model(Path(candidate))
    except ArtifactInspectionError as error:
        raise NumericalDiffError(str(error)) from error

    baseline_values = _typed_values(baseline_model)
    candidate_values = _typed_values(candidate_model)
    if max(len(baseline_values), len(candidate_values)) > MAX_NUMERICAL_TENSORS:
        raise NumericalDiffError("typed tensor count exceeds the numerical diff limit")

    common_names = frozenset(
        set(baseline_values)
        & set(candidate_values)
        & _produced_names(baseline_model)
        & _produced_names(candidate_model)
    )
    tensor_names = _ordered_outputs(baseline_model, common_names)
    if not tensor_names:
        raise NumericalDiffError("the ONNX graphs expose no comparable tensor names")
    if len(tensor_names) > MAX_NUMERICAL_TENSORS:
        raise NumericalDiffError("comparable tensor count exceeds the numerical diff limit")

    return _LoadedGraphs(
        baseline_profile=baseline_profile,
        candidate_profile=candidate_profile,
        baseline_model=baseline_model,
        candidate_model=candidate_model,
        baseline_values=baseline_values,
        candidate_values=candidate_values,
        common_names=common_names,
        tensor_names=tensor_names,
    )


def _load_runtime() -> tuple[Any, Any]:
    try:
        import numpy as np

        os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")
        import onnxruntime as ort  # type: ignore[import-untyped]
    except ImportError as error:
        raise NumericalDiffError("numerical diff requires the optional 'onnx' extra") from error
    return np, ort


def _create_sessions(
    graphs: _LoadedGraphs, ort: Any
) -> tuple[Any, Any, Sequence[Any], Sequence[Any]]:
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    try:
        baseline_session = ort.InferenceSession(
            _instrument(graphs.baseline_model, graphs.tensor_names),
            options,
            providers=["CPUExecutionProvider"],
        )
        candidate_session = ort.InferenceSession(
            _instrument(graphs.candidate_model, graphs.tensor_names),
            options,
            providers=["CPUExecutionProvider"],
        )
        baseline_inputs = baseline_session.get_inputs()
        candidate_inputs = candidate_session.get_inputs()
    except Exception:
        raise NumericalDiffError("ONNX Runtime numerical comparison failed") from None

    baseline_signature = [(item.name, len(item.shape)) for item in baseline_inputs]
    candidate_signature = [(item.name, len(item.shape)) for item in candidate_inputs]
    if baseline_signature != candidate_signature:
        raise NumericalDiffError("ONNX graph input signatures are incompatible")
    return baseline_session, candidate_session, baseline_inputs, candidate_inputs


def _accumulate_tensor(
    accumulator: _Accumulator,
    baseline_value: Any,
    candidate_value: Any,
    np: Any,
    *,
    absolute_tolerance: float,
    relative_tolerance: float,
    tensor_name: str,
) -> int:
    baseline = np.asarray(baseline_value)
    candidate = np.asarray(candidate_value)
    if baseline.shape != candidate.shape:
        raise NumericalDiffError(f"shared tensor {tensor_name!r} changed shape")
    if baseline.size == 0:
        raise NumericalDiffError("numerical diff does not compare empty tensors")
    if baseline.size > MAX_ELEMENTS_PER_TENSOR:
        raise NumericalDiffError("an output tensor exceeds the element budget")
    if baseline.dtype.kind not in "biuf" or candidate.dtype.kind not in "biuf":
        raise NumericalDiffError("numerical diff only supports numeric tensors")

    baseline64 = baseline.astype(np.float64, copy=False).reshape(-1)
    candidate64 = candidate.astype(np.float64, copy=False).reshape(-1)
    delta = candidate64 - baseline64
    absolute = np.abs(delta)
    relative = absolute / np.maximum(np.abs(baseline64), 1e-12)
    shape = tuple(int(value) for value in baseline.shape)
    if accumulator.shape is None:
        accumulator.shape = shape
    elif accumulator.shape != shape:
        accumulator.shape_changed = True
    accumulator.baseline_dtype = str(baseline.dtype)
    accumulator.candidate_dtype = str(candidate.dtype)
    accumulator.count += int(baseline64.size)
    accumulator.abs_sum += float(np.sum(absolute))
    accumulator.sq_sum += float(np.dot(delta, delta))
    accumulator.max_abs = max(accumulator.max_abs, float(np.max(absolute)))
    accumulator.max_rel = max(accumulator.max_rel, float(np.max(relative)))
    accumulator.dot += float(np.dot(baseline64, candidate64))
    accumulator.baseline_sq += float(np.dot(baseline64, baseline64))
    accumulator.candidate_sq += float(np.dot(candidate64, candidate64))
    accumulator.within = accumulator.within and bool(
        np.allclose(
            baseline64,
            candidate64,
            atol=absolute_tolerance,
            rtol=relative_tolerance,
        )
    )
    return int(baseline.size) * 2


def _compare_cases(
    graphs: _LoadedGraphs,
    sessions: tuple[Any, Any, Sequence[Any], Sequence[Any]],
    cases: Sequence[EvalCase],
    np: Any,
    *,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> dict[str, _Accumulator]:
    baseline_session, candidate_session, baseline_inputs, candidate_inputs = sessions
    accumulators = {name: _Accumulator() for name in graphs.tensor_names}
    output_elements = 0
    try:
        for case in cases:
            baseline_feed = _feeds(case, baseline_inputs, np)
            candidate_feed = _feeds(case, candidate_inputs, np)
            baseline_outputs = baseline_session.run(list(graphs.tensor_names), baseline_feed)
            candidate_outputs = candidate_session.run(list(graphs.tensor_names), candidate_feed)
            for name, baseline_value, candidate_value in zip(
                graphs.tensor_names, baseline_outputs, candidate_outputs, strict=True
            ):
                output_elements += _accumulate_tensor(
                    accumulators[name],
                    baseline_value,
                    candidate_value,
                    np,
                    absolute_tolerance=absolute_tolerance,
                    relative_tolerance=relative_tolerance,
                    tensor_name=name,
                )
                if output_elements > MAX_TOTAL_ELEMENTS:
                    raise NumericalDiffError("outputs exceed the numerical diff element budget")
    except NumericalDiffError:
        raise
    except Exception:
        raise NumericalDiffError("ONNX Runtime numerical comparison failed") from None
    return accumulators


def _tensor_diffs(
    tensor_names: Sequence[str], accumulators: Mapping[str, _Accumulator]
) -> tuple[TensorNumericalDiff, ...]:
    results: list[TensorNumericalDiff] = []
    for name in tensor_names:
        accumulator = accumulators[name]
        denominator = math.sqrt(accumulator.baseline_sq * accumulator.candidate_sq)
        cosine = accumulator.dot / denominator if denominator else 1.0
        results.append(
            TensorNumericalDiff(
                name=name,
                baseline_dtype=accumulator.baseline_dtype,
                candidate_dtype=accumulator.candidate_dtype,
                shape=None if accumulator.shape_changed else accumulator.shape,
                element_count=accumulator.count,
                max_abs_error=accumulator.max_abs,
                mean_abs_error=accumulator.abs_sum / accumulator.count,
                rmse=math.sqrt(accumulator.sq_sum / accumulator.count),
                max_relative_error=accumulator.max_rel,
                cosine_similarity=max(-1.0, min(1.0, cosine)),
                within_tolerance=accumulator.within,
            )
        )
    return tuple(results)


def compare_onnx_numerics(
    baseline: str | Path,
    candidate: str | Path,
    cases: Sequence[EvalCase],
    *,
    absolute_tolerance: float = 1e-5,
    relative_tolerance: float = 1e-4,
) -> NumericalDiff:
    """Execute shared intermediate tensors and locate the first numerical drift."""
    _validate_request(cases, absolute_tolerance, relative_tolerance)
    graphs = _load_graphs(baseline, candidate)
    np, ort = _load_runtime()
    sessions = _create_sessions(graphs, ort)
    accumulators = _compare_cases(
        graphs,
        sessions,
        cases,
        np,
        absolute_tolerance=absolute_tolerance,
        relative_tolerance=relative_tolerance,
    )
    tensor_diffs = _tensor_diffs(graphs.tensor_names, accumulators)
    first_divergent = next((item.name for item in tensor_diffs if not item.within_tolerance), None)
    payload = {
        "baseline_profile_id": graphs.baseline_profile.id,
        "candidate_profile_id": graphs.candidate_profile.id,
        "case_count": len(cases),
        "absolute_tolerance": absolute_tolerance,
        "relative_tolerance": relative_tolerance,
        "baseline_only_tensors": tuple(
            sorted(set(graphs.baseline_values) - graphs.common_names)
        ),
        "candidate_only_tensors": tuple(
            sorted(set(graphs.candidate_values) - graphs.common_names)
        ),
        "tensors": tensor_diffs,
        "first_divergent_tensor": first_divergent,
    }
    identifier = fingerprint(payload, namespace="onnx-numerical-diff")
    return NumericalDiff(id=f"mcr:sha256:{identifier}", **payload)
