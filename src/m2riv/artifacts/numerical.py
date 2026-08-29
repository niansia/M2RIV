"""Bounded, CPU-only per-tensor numerical diff for self-contained ONNX graphs."""

from __future__ import annotations

import math
import os
from collections.abc import Sequence
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


def _ordered_outputs(model: Any, available: set[str]) -> tuple[str, ...]:
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


def compare_onnx_numerics(
    baseline: str | Path,
    candidate: str | Path,
    cases: Sequence[EvalCase],
    *,
    absolute_tolerance: float = 1e-5,
    relative_tolerance: float = 1e-4,
) -> NumericalDiff:
    """Execute shared intermediate tensors and locate the first numerical drift."""
    if not cases or len(cases) > MAX_NUMERICAL_CASES:
        raise ValueError(f"numerical diff requires 1 to {MAX_NUMERICAL_CASES} cases")
    if (
        not math.isfinite(absolute_tolerance)
        or not math.isfinite(relative_tolerance)
        or absolute_tolerance < 0
        or relative_tolerance < 0
    ):
        raise ValueError("numerical diff tolerances must be finite and non-negative")
    baseline_path = Path(baseline)
    candidate_path = Path(candidate)
    try:
        baseline_profile, baseline_model = _load_model(baseline_path)
        candidate_profile, candidate_model = _load_model(candidate_path)
    except ArtifactInspectionError as error:
        raise NumericalDiffError(str(error)) from error
    baseline_values = _typed_values(baseline_model)
    candidate_values = _typed_values(candidate_model)
    if (
        len(baseline_values) > MAX_NUMERICAL_TENSORS
        or len(candidate_values) > MAX_NUMERICAL_TENSORS
    ):
        raise NumericalDiffError("typed tensor count exceeds the numerical diff limit")
    common = (
        set(baseline_values)
        & set(candidate_values)
        & _produced_names(baseline_model)
        & _produced_names(candidate_model)
    )
    ordered = _ordered_outputs(baseline_model, common)
    if not ordered:
        raise NumericalDiffError("the ONNX graphs expose no comparable tensor names")
    if len(ordered) > MAX_NUMERICAL_TENSORS:
        raise NumericalDiffError("comparable tensor count exceeds the numerical diff limit")
    try:
        import numpy as np

        os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")
        import onnxruntime as ort  # type: ignore[import-untyped]
    except ImportError as error:
        raise NumericalDiffError("numerical diff requires the optional 'onnx' extra") from error

    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    try:
        baseline_bytes = _instrument(baseline_model, ordered)
        candidate_bytes = _instrument(candidate_model, ordered)
        baseline_session = ort.InferenceSession(
            baseline_bytes, options, providers=["CPUExecutionProvider"]
        )
        candidate_session = ort.InferenceSession(
            candidate_bytes, options, providers=["CPUExecutionProvider"]
        )
        baseline_inputs = baseline_session.get_inputs()
        candidate_inputs = candidate_session.get_inputs()
        if [(item.name, len(item.shape)) for item in baseline_inputs] != [
            (item.name, len(item.shape)) for item in candidate_inputs
        ]:
            raise NumericalDiffError("ONNX graph input signatures are incompatible")
        accumulators = {name: _Accumulator() for name in ordered}
        total_output_elements = 0
        for case in cases:
            baseline_feed = _feeds(case, baseline_inputs, np)
            candidate_feed = _feeds(case, candidate_inputs, np)
            baseline_outputs = baseline_session.run(list(ordered), baseline_feed)
            candidate_outputs = candidate_session.run(list(ordered), candidate_feed)
            for name, baseline_value, candidate_value in zip(
                ordered, baseline_outputs, candidate_outputs, strict=True
            ):
                left = np.asarray(baseline_value)
                right = np.asarray(candidate_value)
                if left.shape != right.shape:
                    raise NumericalDiffError(f"shared tensor {name!r} changed shape")
                if left.size == 0:
                    raise NumericalDiffError("numerical diff does not compare empty tensors")
                if left.size > MAX_ELEMENTS_PER_TENSOR:
                    raise NumericalDiffError("an output tensor exceeds the element budget")
                total_output_elements += int(left.size) * 2
                if total_output_elements > MAX_TOTAL_ELEMENTS:
                    raise NumericalDiffError("outputs exceed the numerical diff element budget")
                if left.dtype.kind not in "biuf" or right.dtype.kind not in "biuf":
                    raise NumericalDiffError("numerical diff only supports numeric tensors")
                left64 = left.astype(np.float64, copy=False).reshape(-1)
                right64 = right.astype(np.float64, copy=False).reshape(-1)
                delta = right64 - left64
                absolute = np.abs(delta)
                relative = absolute / np.maximum(np.abs(left64), 1e-12)
                item = accumulators[name]
                shape = tuple(int(value) for value in left.shape)
                if item.shape is None:
                    item.shape = shape
                elif item.shape != shape:
                    item.shape_changed = True
                item.baseline_dtype = str(left.dtype)
                item.candidate_dtype = str(right.dtype)
                item.count += int(left64.size)
                item.abs_sum += float(np.sum(absolute))
                item.sq_sum += float(np.dot(delta, delta))
                item.max_abs = max(item.max_abs, float(np.max(absolute)))
                item.max_rel = max(item.max_rel, float(np.max(relative)))
                item.dot += float(np.dot(left64, right64))
                item.baseline_sq += float(np.dot(left64, left64))
                item.candidate_sq += float(np.dot(right64, right64))
                item.within = item.within and bool(
                    np.allclose(
                        left64,
                        right64,
                        atol=absolute_tolerance,
                        rtol=relative_tolerance,
                    )
                )
    except NumericalDiffError:
        raise
    except Exception:
        raise NumericalDiffError("ONNX Runtime numerical comparison failed") from None

    tensor_diffs: list[TensorNumericalDiff] = []
    for name in ordered:
        item = accumulators[name]
        count = item.count
        denominator = math.sqrt(item.baseline_sq * item.candidate_sq)
        cosine = item.dot / denominator if denominator else 1.0
        tensor_diffs.append(
            TensorNumericalDiff(
                name=name,
                baseline_dtype=item.baseline_dtype,
                candidate_dtype=item.candidate_dtype,
                shape=None if item.shape_changed else item.shape,
                element_count=count,
                max_abs_error=item.max_abs,
                mean_abs_error=item.abs_sum / count,
                rmse=math.sqrt(item.sq_sum / count),
                max_relative_error=item.max_rel,
                cosine_similarity=max(-1.0, min(1.0, cosine)),
                within_tolerance=item.within,
            )
        )
    first_divergent = next((item.name for item in tensor_diffs if not item.within_tolerance), None)
    payload = {
        "baseline_profile_id": baseline_profile.id,
        "candidate_profile_id": candidate_profile.id,
        "case_count": len(cases),
        "absolute_tolerance": absolute_tolerance,
        "relative_tolerance": relative_tolerance,
        "baseline_only_tensors": tuple(sorted(set(baseline_values) - common)),
        "candidate_only_tensors": tuple(sorted(set(candidate_values) - common)),
        "tensors": tuple(tensor_diffs),
        "first_divergent_tensor": first_divergent,
    }
    identifier = fingerprint(payload, namespace="onnx-numerical-diff")
    return NumericalDiff(id=f"mcr:sha256:{identifier}", **payload)
