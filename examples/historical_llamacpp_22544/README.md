# Historical replay: llama.cpp #22544

This fixture replays a real llama.cpp quantization regression reported in
[issue #22544](https://github.com/ggml-org/llama.cpp/issues/22544) and fixed by
[PR #22572](https://github.com/ggml-org/llama.cpp/pull/22572).

The upstream report identifies first-bad commit `1dab5f5`. When the requested
`--tensor-type` matched the global quantization type, the explicit choice was not
marked manual and an internal heuristic replaced `iq4_xs` with `q5_K`. The issue
publishes the two affected tensor assignments retained here. Both are critical
artifact-contract cases, so the historical candidate is blocked.

```console
merriv compare \
  examples/historical_llamacpp_22544/baseline.jsonl \
  examples/historical_llamacpp_22544/candidate.jsonl \
  --suite examples/historical_llamacpp_22544/suite.jsonl \
  --policy examples/historical_llamacpp_22544/policy.yaml \
  --output runs/historical-llamacpp-22544
```

The expected exit code is `2` (`BLOCK`). This is a source-anchored replay of
upstream's published observations, not a fresh execution of the 27B model or a
claim that two tensors establish a model-quality effect. Its purpose is narrower:
it demonstrates that a release contract binding requested and realized tensor
types would have rejected the affected artifact.
