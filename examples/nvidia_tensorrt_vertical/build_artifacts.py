"""Build the PyTorch source and ModelOpt INT8 artifact sequence."""

from __future__ import annotations

import argparse
import base64
import hashlib
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
    print(arguments.output)


if __name__ == "__main__":
    main()
