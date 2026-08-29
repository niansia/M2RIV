"""Optional CPU-only ONNX Runtime adapter for deployment-artifact comparisons."""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from time import perf_counter_ns
from typing import Any, Literal

from m2riv.adapters.base import AdapterCapability
from m2riv.artifacts import ArtifactInspectionError, inspect_artifact
from m2riv.core.identity import build_local_snapshot, fingerprint
from m2riv.core.models import EvalCase, ModelFamily, ModelSnapshot, Observation, RuntimeProfile

MAX_INPUT_ELEMENTS = 4_000_000
MAX_OUTPUT_ELEMENTS = 4_000_000


class OnnxRuntimeError(ValueError):
    """An ONNX Runtime execution boundary failed without exposing model data."""


def _safe_io_name(value: str, *, label: str) -> str:
    if not value or len(value) > 512 or any(not character.isprintable() for character in value):
        raise OnnxRuntimeError(f"ONNX {label} name is invalid")
    return value


class OnnxRuntimeAdapter:
    """Execute one self-contained ONNX graph with the CPU execution provider.

    The adapter never registers custom-op libraries and refuses external tensor
    data. Native runtime parsing is still not a sandbox; untrusted artifacts
    should be inspected and executed in an OS-isolated worker.
    """

    def __init__(
        self,
        model_path: str | Path,
        *,
        model_family: ModelFamily = ModelFamily.CUSTOM,
        input_name: str | None = None,
        output_name: str | None = None,
        output_mode: Literal["identity", "argmax"] = "identity",
        intra_op_threads: int = 1,
    ) -> None:
        if (
            isinstance(intra_op_threads, bool)
            or not isinstance(intra_op_threads, int)
            or not 1 <= intra_op_threads <= 256
        ):
            raise ValueError("intra_op_threads must be an integer between 1 and 256")
        source = Path(model_path)
        try:
            artifact_profile = inspect_artifact(source)
        except ArtifactInspectionError as error:
            raise OnnxRuntimeError(str(error)) from error
        if artifact_profile.onnx is None:
            raise OnnxRuntimeError("artifact must contain exactly one inspectable ONNX model")
        if artifact_profile.onnx.uses_external_data:
            raise OnnxRuntimeError("external ONNX tensor data is not supported")
        try:
            import numpy as np
            import onnxruntime as ort  # type: ignore[import-untyped]

            options = ort.SessionOptions()
            options.intra_op_num_threads = intra_op_threads
            options.inter_op_num_threads = 1
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            session = ort.InferenceSession(
                str(source),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
        except ImportError as error:
            raise OnnxRuntimeError(
                "ONNX execution requires the optional 'onnx' extra"
            ) from error
        except Exception:
            raise OnnxRuntimeError("ONNX Runtime could not create a CPU session") from None

        inputs = session.get_inputs()
        outputs = session.get_outputs()
        if not inputs or not outputs:
            raise OnnxRuntimeError("ONNX graph must expose at least one input and output")
        selected_input = input_name or inputs[0].name
        selected_output = output_name or outputs[0].name
        input_metadata = next((item for item in inputs if item.name == selected_input), None)
        if input_metadata is None:
            raise OnnxRuntimeError("requested ONNX input does not exist")
        if not any(item.name == selected_output for item in outputs):
            raise OnnxRuntimeError("requested ONNX output does not exist")
        input_type = input_metadata.type
        numpy_dtype = {
            "tensor(float)": np.float32,
            "tensor(float16)": np.float16,
            "tensor(double)": np.float64,
            "tensor(int64)": np.int64,
            "tensor(int32)": np.int32,
        }.get(input_type)
        if numpy_dtype is None:
            raise OnnxRuntimeError(f"unsupported ONNX input type: {input_type}")

        self._source = source
        self._session = session
        self._numpy = np
        self._input_name = _safe_io_name(selected_input, label="input")
        self._output_name = _safe_io_name(selected_output, label="output")
        self._input_rank = len(input_metadata.shape)
        self._numpy_dtype = numpy_dtype
        self._output_mode = output_mode
        self._runtime_version = _safe_io_name(ort.__version__, label="runtime version")
        self._snapshot = build_local_snapshot(
            source,
            model_family=model_family,
            runtime_profile=RuntimeProfile(
                framework="onnxruntime",
                device="cpu",
                dtype=input_type.removeprefix("tensor(").removesuffix(")"),
            ),
            execution_config={
                "adapter": "onnxruntime-cpu-v1",
                "onnxruntime": self._runtime_version,
                "provider": "CPUExecutionProvider",
                "input_name": self._input_name,
                "output_name": self._output_name,
                "output_mode": output_mode,
                "intra_op_threads": intra_op_threads,
            },
        )
        self._adapter_fingerprint = fingerprint(
            {
                "snapshot": self._snapshot.id,
                "runtime": self._runtime_version,
                "input": self._input_name,
                "output": self._output_name,
                "mode": output_mode,
                "threads": intra_op_threads,
            },
            namespace="onnx-runtime-adapter",
        )

    @property
    def adapter_fingerprint(self) -> str:
        return self._adapter_fingerprint

    def describe(self) -> ModelSnapshot:
        return self._snapshot

    def capabilities(self) -> frozenset[AdapterCapability]:
        return frozenset(
            {AdapterCapability.BATCH, AdapterCapability.HARDWARE_METRICS}
        )

    def _case_input(self, case: EvalCase) -> Any:
        value = case.input
        if isinstance(value, dict):
            if set(value) != {self._input_name}:
                raise OnnxRuntimeError("case input mapping must match the selected ONNX input")
            value = value[self._input_name]
        try:
            array = self._numpy.asarray(value, dtype=self._numpy_dtype)
        except Exception:
            raise OnnxRuntimeError("case input could not be converted to the ONNX dtype") from None
        if array.size > MAX_INPUT_ELEMENTS:
            raise OnnxRuntimeError(
                f"case input exceeds {MAX_INPUT_ELEMENTS} element limit"
            )
        if array.ndim == self._input_rank - 1:
            array = self._numpy.expand_dims(array, axis=0)
        if array.ndim != self._input_rank:
            raise OnnxRuntimeError("case input rank does not match the ONNX graph")
        return array

    def _normalize_output(self, value: Any) -> Any:
        array = self._numpy.asarray(value)
        if array.size > MAX_OUTPUT_ELEMENTS:
            raise OnnxRuntimeError(
                f"ONNX output exceeds {MAX_OUTPUT_ELEMENTS} element limit"
            )
        if self._output_mode == "argmax":
            array = self._numpy.asarray(self._numpy.argmax(array, axis=-1))
        if array.size == 1:
            return array.reshape(-1)[0].item()
        if array.ndim >= 1 and array.shape[0] == 1:
            array = array[0]
        return array.tolist()

    def run(
        self,
        cases: Sequence[EvalCase],
        profile: RuntimeProfile,
    ) -> tuple[Observation, ...]:
        if profile.device not in {None, "cpu"}:
            raise OnnxRuntimeError("this adapter only supports the CPU device")
        observations: list[Observation] = []
        for case in cases:
            value = self._case_input(case)
            elapsed_ns = 0
            raw_output: Any = None
            try:
                for _ in range(profile.repetitions):
                    started = perf_counter_ns()
                    raw_output = self._session.run(
                        [self._output_name], {self._input_name: value}
                    )[0]
                    elapsed_ns += perf_counter_ns() - started
            except Exception:
                raise OnnxRuntimeError("ONNX Runtime inference failed") from None
            output = self._normalize_output(raw_output)
            latency_ms = elapsed_ns / profile.repetitions / 1_000_000
            if not math.isfinite(latency_ms) or latency_ms < 0:
                raise OnnxRuntimeError("ONNX Runtime returned invalid timing evidence")
            output_digest = fingerprint(output, namespace="observation-output")
            observation_payload = {
                "snapshot_id": self._snapshot.id,
                "case_id": case.case_id,
                "attempt": 0,
                "seed": profile.seed,
                "output_digest": output_digest,
            }
            observation_id = fingerprint(observation_payload, namespace="observation")
            observations.append(
                Observation(
                    id=f"m2riv:sha256:{observation_id}",
                    snapshot_id=self._snapshot.id,
                    case_id=case.case_id,
                    seed=profile.seed,
                    output=output,
                    output_digest=output_digest,
                    latency_ms=latency_ms,
                    traces={
                        "execution_provider": "CPUExecutionProvider",
                        "runtime": self._runtime_version,
                    },
                )
            )
        return tuple(observations)
