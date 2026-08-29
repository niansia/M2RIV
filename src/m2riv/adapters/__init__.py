"""Model source adapter contracts and reference implementations."""

from m2riv.adapters.base import AdapterCapability, ModelAdapter
from m2riv.adapters.fake import FakeAdapter
from m2riv.adapters.onnx_runtime import OnnxRuntimeAdapter, OnnxRuntimeError
from m2riv.adapters.openai_compatible import OpenAICompatibleAdapter, OpenAICompatibleError
from m2riv.adapters.recorded import RecordedAdapter, RecordedOutput

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
