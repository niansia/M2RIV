"""Model source adapter contracts and reference implementations."""

from merriv.adapters.base import AdapterCapability, ModelAdapter
from merriv.adapters.fake import FakeAdapter
from merriv.adapters.onnx_runtime import OnnxRuntimeAdapter, OnnxRuntimeError
from merriv.adapters.openai_compatible import OpenAICompatibleAdapter, OpenAICompatibleError
from merriv.adapters.recorded import RecordedAdapter, RecordedOutput

__all__ = [
    "AdapterCapability",
    "FakeAdapter",
    "ModelAdapter",
    "OnnxRuntimeAdapter",
    "OnnxRuntimeError",
    "OpenAICompatibleAdapter",
    "OpenAICompatibleError",
    "RecordedAdapter",
    "RecordedOutput",
]
