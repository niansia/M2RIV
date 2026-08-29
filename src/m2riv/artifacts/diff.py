"""Deterministic semantic diff for inspected deployment artifacts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from m2riv.artifacts.models import (
    ArtifactDiff,
    ArtifactProfile,
    NamedCountChange,
    OnnxCount,
    OpsetChange,
)
from m2riv.core.identity import fingerprint


def _counts(items: Iterable[OnnxCount]) -> dict[str, int]:
    return {item.name: item.count for item in items}


def _count_changes(
    baseline: Mapping[str, int], candidate: Mapping[str, int]
) -> tuple[NamedCountChange, ...]:
    return tuple(
        NamedCountChange(
            name=name,
            baseline=baseline.get(name, 0),
            candidate=candidate.get(name, 0),
            delta=candidate.get(name, 0) - baseline.get(name, 0),
        )
        for name in sorted(baseline.keys() | candidate.keys())
        if baseline.get(name, 0) != candidate.get(name, 0)
    )


def compare_artifacts(baseline: ArtifactProfile, candidate: ArtifactProfile) -> ArtifactDiff:
    """Compare profiles without reopening or executing their source artifacts."""
    baseline_components = {
        role: tuple(
            sorted(
                (component.relative_path, component.digest)
                for component in baseline.components
                if component.role == role
            )
        )
        for role in {component.role for component in baseline.components}
    }
    candidate_components = {
        role: tuple(
            sorted(
                (component.relative_path, component.digest)
                for component in candidate.components
                if component.role == role
            )
        )
        for role in {component.role for component in candidate.components}
    }
    changed_components = tuple(
        role
        for role in sorted(baseline_components.keys() | candidate_components.keys())
        if baseline_components.get(role) != candidate_components.get(role)
    )

    if baseline.onnx is None or candidate.onnx is None:
        opset_changes: tuple[OpsetChange, ...] = ()
        operator_changes: tuple[NamedCountChange, ...] = ()
        dtype_changes: tuple[NamedCountChange, ...] = ()
        node_delta = None
        initializer_delta = None
        parameter_delta = None
        inputs_changed = None
        outputs_changed = None
        external_data_changed = None
        quantization_format_changed = None
    else:
        baseline_opsets = {item.domain: item.version for item in baseline.onnx.opsets}
        candidate_opsets = {item.domain: item.version for item in candidate.onnx.opsets}
        opset_changes = tuple(
            OpsetChange(
                domain=domain,
                baseline=baseline_opsets.get(domain),
                candidate=candidate_opsets.get(domain),
            )
            for domain in sorted(baseline_opsets.keys() | candidate_opsets.keys())
            if baseline_opsets.get(domain) != candidate_opsets.get(domain)
        )
        operator_changes = _count_changes(
            _counts(baseline.onnx.operator_counts),
            _counts(candidate.onnx.operator_counts),
        )
        dtype_changes = _count_changes(
            _counts(baseline.onnx.initializer_dtype_counts),
            _counts(candidate.onnx.initializer_dtype_counts),
        )
        node_delta = candidate.onnx.node_count - baseline.onnx.node_count
        initializer_delta = candidate.onnx.initializer_count - baseline.onnx.initializer_count
        parameter_delta = candidate.onnx.parameter_count - baseline.onnx.parameter_count
        inputs_changed = candidate.onnx.inputs != baseline.onnx.inputs
        outputs_changed = candidate.onnx.outputs != baseline.onnx.outputs
        external_data_changed = (
            candidate.onnx.uses_external_data != baseline.onnx.uses_external_data
        )
        quantization_format_changed = (
            candidate.onnx.quantization_format != baseline.onnx.quantization_format
        )

    payload = {
        "baseline_profile_id": baseline.id,
        "candidate_profile_id": candidate.id,
        "artifact_changed": baseline.artifact.digest != candidate.artifact.digest,
        "format_changed": baseline.format != candidate.format,
        "size_delta_bytes": candidate.artifact.size_bytes - baseline.artifact.size_bytes,
        "file_count_delta": candidate.artifact.file_count - baseline.artifact.file_count,
        "changed_components": changed_components,
        "opset_changes": opset_changes,
        "operator_changes": operator_changes,
        "initializer_dtype_changes": dtype_changes,
        "node_count_delta": node_delta,
        "initializer_count_delta": initializer_delta,
        "parameter_count_delta": parameter_delta,
        "inputs_changed": inputs_changed,
        "outputs_changed": outputs_changed,
        "external_data_changed": external_data_changed,
        "quantization_format_changed": quantization_format_changed,
    }
    diff_id = fingerprint(payload, namespace="artifact-diff")
    return ArtifactDiff(
        id=f"mcr:sha256:{diff_id}",
        baseline_profile_id=baseline.id,
        candidate_profile_id=candidate.id,
        artifact_changed=baseline.artifact.digest != candidate.artifact.digest,
        format_changed=baseline.format != candidate.format,
        size_delta_bytes=candidate.artifact.size_bytes - baseline.artifact.size_bytes,
        file_count_delta=candidate.artifact.file_count - baseline.artifact.file_count,
        changed_components=changed_components,
        opset_changes=opset_changes,
        operator_changes=operator_changes,
        initializer_dtype_changes=dtype_changes,
        node_count_delta=node_delta,
        initializer_count_delta=initializer_delta,
        parameter_count_delta=parameter_delta,
        inputs_changed=inputs_changed,
        outputs_changed=outputs_changed,
        external_data_changed=external_data_changed,
        quantization_format_changed=quantization_format_changed,
    )
