"""Polygraphy data loader for the fixed Merriv digits suite."""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np


def load_data() -> list[dict[str, np.ndarray]]:
    """Load a bounded case cohort selected by the vertical orchestrator."""
    source_value = os.environ.get("MERRIV_NVIDIA_SUITE")
    if not source_value:
        raise ValueError("MERRIV_NVIDIA_SUITE must point to the generated suite.jsonl")
    limit = int(os.environ.get("MERRIV_NVIDIA_CASES", "128"))
    if not 1 <= limit <= 10_000:
        raise ValueError("MERRIV_NVIDIA_CASES must be between 1 and 10000")
    source = Path(source_value)
    if source.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("GPU suite exceeds the data-loader size limit")
    loaded: list[dict[str, np.ndarray]] = []
    with source.open("r", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            values = np.asarray(row["input"], dtype=np.float32)
            if values.shape != (64,):
                raise ValueError("GPU vertical expects a 64-element digits input")
            loaded.append({"input": values.reshape(1, 64)})
            if len(loaded) == limit:
                break
    if len(loaded) != limit:
        raise ValueError(f"GPU suite contains fewer than {limit} cases")
    return loaded
