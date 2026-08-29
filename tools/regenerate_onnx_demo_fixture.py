"""Regenerate the reviewed sklearn MLP fixture used by the ONNX demo.

Training libraries can produce different floating-point weights across BLAS
implementations. Regeneration is therefore an explicit maintainer operation:
review the resulting SHA-256 and cross-platform demo evidence before replacing
the checked-in fixture or its pinned digest.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import runpy
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import numpy as np
import onnx
from onnx import TensorProto
from sklearn.datasets import load_digits
from sklearn.model_selection import train_test_split
from sklearn.neural_network import MLPClassifier

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "onnx_quantization" / "run_demo.py"
DEFAULT_OUTPUT = (
    ROOT
    / "examples"
    / "onnx_quantization"
    / "assets"
    / "digits-mlp-fp32.onnx.b64"
)
SEED = 23
RARE_DIGIT = 1


def regenerate(output: Path) -> str:
    digits = load_digits()
    features = digits.data.astype(np.float32) / 16.0
    labels = digits.target.astype(np.int64)
    train_x, _, train_y, _ = train_test_split(
        features,
        labels,
        test_size=0.35,
        random_state=SEED,
        stratify=labels,
    )
    rare_indices = np.flatnonzero(train_y == RARE_DIGIT)
    common_indices = np.flatnonzero(train_y != RARE_DIGIT)
    retained = np.concatenate(
        (common_indices, rare_indices[: len(rare_indices) // 4])
    )
    np.random.default_rng(SEED).shuffle(retained)
    classifier = MLPClassifier(
        hidden_layer_sizes=(32,),
        activation="relu",
        solver="lbfgs",
        alpha=1e-4,
        max_iter=500,
        random_state=SEED,
    )
    classifier.fit(train_x[retained], train_y[retained])

    namespace = runpy.run_path(str(DEMO))
    make_model = cast(Callable[..., onnx.ModelProto], namespace["_make_onnx_model"])
    weights: dict[str, np.ndarray[Any, Any]] = {
        "w0": classifier.coefs_[0],
        "b0": classifier.intercepts_[0],
        "w1": classifier.coefs_[1],
        "b1": classifier.intercepts_[1],
    }
    model = make_model(
        weights,
        numpy_dtype=np.dtype(np.float32),
        tensor_type=TensorProto.FLOAT,
    )
    payload = model.SerializeToString()
    digest = hashlib.sha256(payload).hexdigest()
    encoded = base64.b64encode(payload).decode("ascii")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(textwrap.wrap(encoded, 100)) + "\n", "ascii")
    return digest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    digest = regenerate(arguments.output)
    print(f"Wrote {arguments.output}")
    print(f"SHA-256: {digest}")


if __name__ == "__main__":
    main()
