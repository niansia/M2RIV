"""Build the PyTorch source and ModelOpt INT8 artifact sequence."""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import onnx
import torch
from modelopt.onnx.quantization import quantize
from onnx import numpy_helper
from sklearn.datasets import load_digits
from sklearn.model_selection import train_test_split

FIXTURE_SHA256 = "1d6652110add0355b2c6f4e2ab5aee63be1690384d41c79dc6eff201afd3bdb7"
SEED = 23


class DigitsConv(torch.nn.Module):
    """1x1-convolution form of the reviewed two-layer digits MLP."""

    def __init__(self, weights: dict[str, np.ndarray[Any, Any]]) -> None:
        super().__init__()
        self.hidden = torch.nn.Conv1d(64, 32, kernel_size=1)
        self.output = torch.nn.Conv1d(32, 10, kernel_size=1)
        with torch.no_grad():
            self.hidden.weight.copy_(torch.from_numpy(weights["w0"].T[:, :, None]))
            self.hidden.bias.copy_(torch.from_numpy(weights["b0"]))
            self.output.weight.copy_(torch.from_numpy(weights["w1"].T[:, :, None]))
            self.output.bias.copy_(torch.from_numpy(weights["b1"]))

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        hidden = torch.relu(self.hidden(values.unsqueeze(-1)))
        return self.output(hidden).squeeze(-1)


def _weights(fixture: Path) -> dict[str, np.ndarray[Any, Any]]:
    payload = base64.b64decode("".join(fixture.read_text(encoding="ascii").split()))
    actual = hashlib.sha256(payload).hexdigest()
    if actual != FIXTURE_SHA256:
        raise ValueError(f"source fixture digest changed: {actual}")
    model = onnx.load_model_from_string(payload)
    weights = {item.name: numpy_helper.to_array(item).copy() for item in model.graph.initializer}
    if set(weights) != {"w0", "b0", "w1", "b1"}:
        raise ValueError("source fixture has an unexpected initializer contract")
    return weights


def _export_source(fixture: Path, output: Path) -> None:
    model = DigitsConv(_weights(fixture)).eval()
    torch.onnx.export(
        model,
        (torch.zeros((1, 64), dtype=torch.float32),),
        output,
        input_names=["input"],
        output_names=["logits"],
        opset_version=17,
        dynamo=False,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _source_commit() -> str | None:
    candidate = os.environ.get("GITHUB_SHA")
    if candidate and len(candidate) in {40, 64}:
        return candidate.lower()
    git = shutil.which("git")
    if git is None:
        return None
    completed = subprocess.run(  # noqa: S603 - resolved local Git executable, fixed argv.
        [git, "rev-parse", "HEAD"], check=False, capture_output=True, text=True
    )
    value = completed.stdout.strip().lower()
    return value if completed.returncode == 0 and len(value) in {40, 64} else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    arguments.output.mkdir(parents=True, exist_ok=True)
    source = arguments.output / "build-00-pytorch-fp32.onnx"
    _export_source(arguments.fixture, source)

    digits = load_digits()
    values = digits.data.astype(np.float32) / 16.0
    labels = digits.target.astype(np.int64)
    train_x, _, _, _ = train_test_split(
        values,
        labels,
        test_size=0.35,
        random_state=SEED,
        stratify=labels,
    )
    cohort = np.ascontiguousarray(train_x[:128])
    cohort_digest = hashlib.sha256(
        b"mcr:nvidia-calibration-cohort:v1\x00"
        + str(cohort.shape).encode("ascii")
        + b"\x00"
        + cohort.dtype.str.encode("ascii")
        + b"\x00"
        + cohort.tobytes()
    ).hexdigest()
    builds = (
        ("build-01-modelopt-int8-balanced.onnx", 1.0),
        ("build-02-modelopt-int8-scale-065.onnx", 0.65),
        ("build-03-modelopt-int8-scale-060.onnx", 0.60),
    )
    for name, scale in builds:
        quantize(
            str(source),
            quantize_mode="int8",
            calibration_data={"input": train_x[:128] * scale},
            calibration_method="max",
            calibration_eps=["cpu"],
            op_types_to_quantize=["Conv"],
            output_path=str(arguments.output / name),
            dq_only=False,
            high_precision_dtype="fp32",
            log_level="WARNING",
        )
    versions = {
        name: importlib.metadata.version(name)
        for name in ("nvidia-modelopt", "numpy", "onnx", "scikit-learn", "torch")
    }
    manifest = {
        "schema_version": "0.1.0",
        "source_commit": _source_commit(),
        "source_fixture_sha256": FIXTURE_SHA256,
        "source_fixture_size_bytes": len(
            base64.b64decode(
                "".join(arguments.fixture.read_text(encoding="ascii").split())
            )
        ),
        "calibration_cohort_sha256": cohort_digest,
        "calibration_case_count": 128,
        "versions": versions,
        "builds": [
            {
                "build_name": "build-00-pytorch-fp16",
                "artifact": source.name,
                "artifact_sha256": _sha256(source),
                "builder": "pytorch",
                "builder_version": versions["torch"],
                "parameters": {"export_opset": 17, "execution_precision": "fp16"},
            },
            *[
                {
                    "build_name": name.removesuffix(".onnx"),
                    "artifact": name,
                    "artifact_sha256": _sha256(arguments.output / name),
                    "builder": "nvidia-modelopt",
                    "builder_version": versions["nvidia-modelopt"],
                    "parameters": {
                        "quantize_mode": "int8",
                        "calibration_method": "max",
                        "calibration_input_scale": scale,
                        "calibration_case_count": 128,
                        "op_types_to_quantize": ["Conv"],
                        "export_opset": 17,
                        "high_precision_dtype": "fp32",
                    },
                }
                for name, scale in builds
            ],
        ],
    }
    (arguments.output / "artifact-build-input.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(arguments.output)


if __name__ == "__main__":
    main()
