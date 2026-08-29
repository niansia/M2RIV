"""Bounded, read-only artifact inspection with optional ONNX support."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Literal

from m2riv.artifacts.models import (
    ArtifactComponent,
    ArtifactFormat,
    ArtifactProfile,
    OnnxCount,
    OnnxGraphSummary,
    OnnxOpset,
    OnnxTensorSpec,
)
from m2riv.core.identity import (
    MAX_ARTIFACT_BYTES,
    MAX_ARTIFACT_ENTRIES,
    MAX_ARTIFACT_FILE_BYTES,
    fingerprint,
    hash_artifact,
    read_verified_file,
)

MAX_ONNX_BYTES = 512 * 1024 * 1024
MAX_ONNX_NODES = 1_000_000
MAX_ONNX_INITIALIZERS = 1_000_000
MAX_ONNX_METADATA = 1024
MAX_ONNX_GRAPHS = 100_000
MAX_ONNX_ATTRIBUTES = 4_000_000
MAX_ONNX_TENSOR_RANK = 32
MAX_ONNX_PARAMETER_COUNT = 1_000_000_000_000_000

_COMPONENT_ROLES = {
    "config.json": "config",
    "generation_config.json": "generation-config",
    "preprocessor_config.json": "preprocessor-config",
    "special_tokens_map.json": "special-tokens",
    "tokenizer.json": "tokenizer",
    "tokenizer_config.json": "tokenizer-config",
}


class ArtifactInspectionError(ValueError):
    """An artifact could not be inspected within the trusted resource boundary."""


def _bounded_text(value: Any, *, label: str, limit: int) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise ArtifactInspectionError(f"ONNX {label} is invalid or exceeds {limit} characters")
    if any(not character.isprintable() for character in value):
        raise ArtifactInspectionError(f"ONNX {label} contains unsupported characters")
    return value


def _tensor_spec(value: Any, onnx: Any) -> OnnxTensorSpec:
    name = _bounded_text(value.name, label="tensor name", limit=512)
    tensor_type = value.type.tensor_type
    if not tensor_type.HasField("shape"):
        dimensions: tuple[str, ...] = ()
    else:
        parsed: list[str] = []
        for dimension in tensor_type.shape.dim:
            if len(parsed) >= MAX_ONNX_TENSOR_RANK:
                raise ArtifactInspectionError(f"ONNX tensor rank exceeds {MAX_ONNX_TENSOR_RANK}")
            if dimension.HasField("dim_value"):
                parsed.append(str(dimension.dim_value))
            elif dimension.HasField("dim_param"):
                parsed.append(
                    _bounded_text(dimension.dim_param, label="symbolic dimension", limit=128) or "?"
                )
            else:
                parsed.append("?")
        dimensions = tuple(parsed)
    try:
        element_type = onnx.TensorProto.DataType.Name(tensor_type.elem_type)
    except ValueError as error:
        raise ArtifactInspectionError("ONNX tensor has an unsupported element type") from error
    return OnnxTensorSpec(name=name, element_type=element_type, shape=dimensions)


def _tensor_elements(value: Any) -> int:
    if len(value.dims) > MAX_ONNX_TENSOR_RANK:
        raise ArtifactInspectionError(f"ONNX tensor rank exceeds {MAX_ONNX_TENSOR_RANK}")
    elements = 1
    for raw_dimension in value.dims:
        dimension = int(raw_dimension)
        if dimension < 0:
            raise ArtifactInspectionError("ONNX initializer dimension must be non-negative")
        elements *= dimension
        if elements > MAX_ONNX_PARAMETER_COUNT:
            raise ArtifactInspectionError(
                f"ONNX parameter count exceeds {MAX_ONNX_PARAMETER_COUNT}"
            )
    return elements


def _uses_external_data(value: Any, onnx: Any) -> bool:
    return bool(value.external_data) or value.data_location == onnx.TensorProto.EXTERNAL


def _walk_graphs(model: Any, onnx: Any) -> tuple[tuple[Any, ...], tuple[Any, ...], bool]:
    graphs: list[Any] = []
    nodes: list[Any] = []
    stack = [model.graph]
    attribute_count = 0
    uses_external_data = False
    while stack:
        graph = stack.pop()
        graphs.append(graph)
        if len(graphs) > MAX_ONNX_GRAPHS:
            raise ArtifactInspectionError(f"ONNX model exceeds {MAX_ONNX_GRAPHS} graph limit")
        nodes.extend(graph.node)
        if len(nodes) > MAX_ONNX_NODES:
            raise ArtifactInspectionError(f"ONNX graph exceeds {MAX_ONNX_NODES} node limit")
        for initializer in graph.initializer:
            uses_external_data = uses_external_data or _uses_external_data(initializer, onnx)
        for sparse in graph.sparse_initializer:
            uses_external_data = (
                uses_external_data
                or _uses_external_data(sparse.values, onnx)
                or _uses_external_data(sparse.indices, onnx)
            )
        for node in graph.node:
            attribute_count += len(node.attribute)
            if attribute_count > MAX_ONNX_ATTRIBUTES:
                raise ArtifactInspectionError(
                    f"ONNX model exceeds {MAX_ONNX_ATTRIBUTES} attribute limit"
                )
            for attribute in node.attribute:
                if attribute.type == onnx.AttributeProto.GRAPH:
                    stack.append(attribute.g)
                elif attribute.type == onnx.AttributeProto.GRAPHS:
                    stack.extend(attribute.graphs)
                elif attribute.type == onnx.AttributeProto.TENSOR:
                    _tensor_elements(attribute.t)
                    uses_external_data = uses_external_data or _uses_external_data(
                        attribute.t, onnx
                    )
                elif attribute.type == onnx.AttributeProto.TENSORS:
                    for tensor in attribute.tensors:
                        _tensor_elements(tensor)
                    uses_external_data = uses_external_data or any(
                        _uses_external_data(tensor, onnx) for tensor in attribute.tensors
                    )
    return tuple(graphs), tuple(nodes), uses_external_data


def _quantization_format(
    operators: Counter[str],
) -> Literal["none", "qdq", "qoperator", "mixed"]:
    has_qdq = any(
        name.endswith("::QuantizeLinear") or name.endswith("::DequantizeLinear")
        for name in operators
    )
    has_qoperator = any(
        name.split("::", 1)[-1].startswith(("QLinear", "MatMulInteger", "ConvInteger"))
        for name in operators
    )
    if has_qdq and has_qoperator:
        return "mixed"
    if has_qdq:
        return "qdq"
    if has_qoperator:
        return "qoperator"
    return "none"


def _inspect_onnx(path: Path, *, max_bytes: int) -> OnnxGraphSummary:
    if isinstance(max_bytes, bool) or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    initial_digest = hash_artifact(
        path,
        max_total_bytes=max_bytes,
        max_file_bytes=max_bytes,
        max_entries=1,
    )
    if initial_digest.size_bytes > max_bytes:
        raise ArtifactInspectionError(f"ONNX artifact exceeds {max_bytes} byte inspection limit")
    try:
        import onnx

        encoded = read_verified_file(
            path,
            max_bytes=max_bytes,
            expected_digest=initial_digest.digest,
        )
        model = onnx.load_model_from_string(encoded)
    except ImportError as error:
        raise ArtifactInspectionError(
            "ONNX inspection requires the optional 'onnx' extra"
        ) from error
    except ValueError as error:
        raise ArtifactInspectionError(str(error)) from error
    except Exception:
        raise ArtifactInspectionError("ONNX artifact could not be parsed") from None

    graph = model.graph
    graphs, nodes, uses_external_data = _walk_graphs(model, onnx)
    initializer_count = sum(len(item.initializer) + len(item.sparse_initializer) for item in graphs)
    if initializer_count > MAX_ONNX_INITIALIZERS:
        raise ArtifactInspectionError(
            f"ONNX graph exceeds {MAX_ONNX_INITIALIZERS} initializer limit"
        )
    if len(model.metadata_props) > MAX_ONNX_METADATA:
        raise ArtifactInspectionError(f"ONNX metadata exceeds {MAX_ONNX_METADATA} entry limit")

    operators: Counter[str] = Counter()
    for node in nodes:
        domain = _bounded_text(node.domain, label="operator domain", limit=128) or "ai.onnx"
        op_type = _bounded_text(node.op_type, label="operator type", limit=128)
        operators[f"{domain}::{op_type}"] += 1

    dtype_counts: Counter[str] = Counter()
    parameter_count = 0
    for current_graph in graphs:
        initializers = list(current_graph.initializer)
        initializers.extend(sparse.values for sparse in current_graph.sparse_initializer)
        for initializer in initializers:
            try:
                dtype = onnx.TensorProto.DataType.Name(initializer.data_type)
            except ValueError as error:
                raise ArtifactInspectionError(
                    "ONNX initializer has an unsupported dtype"
                ) from error
            dtype_counts[dtype] += 1
            parameter_count += _tensor_elements(initializer)
            if parameter_count > MAX_ONNX_PARAMETER_COUNT:
                raise ArtifactInspectionError(
                    f"ONNX parameter count exceeds {MAX_ONNX_PARAMETER_COUNT}"
                )
    opsets = tuple(
        sorted(
            (
                OnnxOpset(
                    domain=_bounded_text(item.domain, label="opset domain", limit=128) or "ai.onnx",
                    version=item.version,
                )
                for item in model.opset_import
            ),
            key=lambda item: item.domain,
        )
    )
    metadata = tuple(
        sorted(
            (
                _bounded_text(item.key, label="metadata key", limit=256),
                _bounded_text(item.value, label="metadata value", limit=4096),
            )
            for item in model.metadata_props
        )
    )
    return OnnxGraphSummary(
        ir_version=model.ir_version,
        producer_name=_bounded_text(model.producer_name, label="producer name", limit=256),
        producer_version=_bounded_text(model.producer_version, label="producer version", limit=128),
        model_version=max(0, model.model_version),
        opsets=opsets,
        node_count=len(nodes),
        initializer_count=initializer_count,
        parameter_count=parameter_count,
        operator_counts=tuple(
            OnnxCount(name=name, count=count) for name, count in sorted(operators.items())
        ),
        initializer_dtype_counts=tuple(
            OnnxCount(name=name, count=count) for name, count in sorted(dtype_counts.items())
        ),
        inputs=tuple(_tensor_spec(value, onnx) for value in graph.input),
        outputs=tuple(_tensor_spec(value, onnx) for value in graph.output),
        uses_external_data=uses_external_data,
        quantization_format=_quantization_format(operators),
        metadata_fingerprint=fingerprint(metadata, namespace="onnx-metadata"),
    )


def _components(
    path: Path,
    *,
    max_onnx_bytes: int,
    max_artifact_bytes: int,
    max_artifact_file_bytes: int,
    max_artifact_entries: int,
) -> tuple[ArtifactComponent, ...]:
    candidates: tuple[Path, ...]
    if path.is_file():
        candidates = (path,)
    else:
        discovered: list[Path] = []
        for entry_count, candidate in enumerate(path.rglob("*"), start=1):
            if entry_count > max_artifact_entries:
                raise ArtifactInspectionError(
                    f"artifact exceeds the {max_artifact_entries} entry traversal budget"
                )
            discovered.append(candidate)
        candidates = tuple(discovered)
    components: list[ArtifactComponent] = []
    for candidate in sorted(candidates, key=lambda item: item.as_posix()):
        if not candidate.is_file():
            continue
        role: str | None
        if candidate.suffix.casefold() == ".onnx":
            role = "model-onnx"
        else:
            role = _COMPONENT_ROLES.get(candidate.name.casefold())
        if role is None:
            continue
        if role == "model-onnx" and candidate.lstat().st_size > max_onnx_bytes:
            raise ArtifactInspectionError(
                f"ONNX artifact exceeds {max_onnx_bytes} byte inspection limit"
            )
        component_budget = min(
            max_artifact_bytes,
            max_artifact_file_bytes,
            max_onnx_bytes if role == "model-onnx" else max_artifact_file_bytes,
        )
        relative = candidate.name if path.is_file() else candidate.relative_to(path).as_posix()
        try:
            digest = hash_artifact(
                candidate,
                max_total_bytes=component_budget,
                max_file_bytes=component_budget,
                max_entries=1,
            )
        except ValueError as error:
            raise ArtifactInspectionError(str(error)) from error
        components.append(
            ArtifactComponent(
                role=role,
                relative_path=relative,
                digest=digest.digest,
                size_bytes=digest.size_bytes,
            )
        )
        if len(components) > 128:
            raise ArtifactInspectionError("artifact exceeds 128 recognized component limit")
    return tuple(components)


def inspect_artifact(
    path: str | Path,
    *,
    max_onnx_bytes: int = MAX_ONNX_BYTES,
    max_artifact_bytes: int = MAX_ARTIFACT_BYTES,
    max_artifact_file_bytes: int = MAX_ARTIFACT_FILE_BYTES,
    max_artifact_entries: int = MAX_ARTIFACT_ENTRIES,
) -> ArtifactProfile:
    """Create a content-addressed semantic profile without executing an artifact."""
    source = Path(path)
    components = _components(
        source,
        max_onnx_bytes=max_onnx_bytes,
        max_artifact_bytes=max_artifact_bytes,
        max_artifact_file_bytes=max_artifact_file_bytes,
        max_artifact_entries=max_artifact_entries,
    )
    try:
        artifact = hash_artifact(
            source,
            max_total_bytes=max_artifact_bytes,
            max_file_bytes=max_artifact_file_bytes,
            max_entries=max_artifact_entries,
        )
    except ValueError as error:
        raise ArtifactInspectionError(str(error)) from error
    onnx_paths = tuple(
        (source if source.is_file() else source / component.relative_path)
        for component in components
        if component.role == "model-onnx"
    )
    onnx_summary = (
        _inspect_onnx(onnx_paths[0], max_bytes=max_onnx_bytes) if len(onnx_paths) == 1 else None
    )
    if source.is_file() and source.suffix.casefold() == ".onnx":
        artifact_format = ArtifactFormat.ONNX
    elif source.is_dir():
        artifact_format = ArtifactFormat.DIRECTORY
    else:
        artifact_format = ArtifactFormat.FILE
    payload = {
        "format": artifact_format,
        "artifact": artifact,
        "components": components,
        "onnx": onnx_summary,
    }
    profile_id = fingerprint(payload, namespace="artifact-profile")
    return ArtifactProfile(
        id=f"mcr:sha256:{profile_id}",
        format=artifact_format,
        artifact=artifact,
        components=components,
        onnx=onnx_summary,
    )
