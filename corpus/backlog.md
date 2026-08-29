# Corpus acquisition backlog

These are acquisition targets, not verified cases and not adoption claims:

1. TensorRT tactic change with quality-stable latency regression.
2. TensorRT version upgrade with first divergent layer.
3. ModelOpt FP8 or NVFP4 deployment regression on an eligible GPU.
4. Execution-provider change with target-specific numerical drift.
5. Tokenizer/config sidecar mismatch with unchanged weights.
6. Precision overflow localized by Polygraphy layer outputs.
7. Dynamic-shape profile error that passes static parsing but fails target E2E.
8. Jetson/DLA unsupported-operator or fallback regression.
9. Compiler-build sequence with a non-monotonic PASS/BLOCK reversal.

Promotion into `index.json` requires exact artifacts or immutable revisions,
reproduction commands, expected decision, retained evidence, limitations, and an
independent rerun when external hardware is involved.
