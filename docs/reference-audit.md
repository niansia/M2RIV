# Blueprint reference audit

Audit date: 2026-08-29. This document supersedes the reference hygiene of the
2026-08-28 blueprint PDF. A reference is acceptable only when its exact primary
URL is recorded and the cited claim is visible at that URL.

## Corrected technical references

- R1: [OpenAI deployment simulation](https://openai.com/index/deployment-simulation/)
- R2: [Anthropic, Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- R3: [Google DeepMind Frontier Safety Framework](https://deepmind.google/discover/blog/introducing-the-frontier-safety-framework/)
- R4: [MLflow Model Registry workflows](https://mlflow.org/docs/latest/ml/model-registry/workflow/)
- R5: [Hugging Face Model Cards](https://huggingface.co/docs/hub/model-cards)
- R6: [MadryLab/modeldiff](https://github.com/MadryLab/modeldiff)
- R7: [teilomillet/vauban](https://github.com/teilomillet/vauban)
- R8a: [dcdeve/tracepact](https://github.com/dcdeve/tracepact)
- R8b: [hidai25/eval-view](https://github.com/hidai25/eval-view)
- R9: [sulthonzh/prompt-bisect](https://github.com/sulthonzh/prompt-bisect)

R8 and R9 were not fictitious, but the PDF's bare “GitHub” citations were not
auditable. The paths above are now mandatory anywhere those comparisons appear.

## Newly required competitors

- [Promptfoo joining OpenAI](https://www.promptfoo.dev/blog/promptfoo-joining-openai/)
- [DeepEval introduction](https://deepeval.com/docs/introduction)
- [Confident AI deployment gate](https://www.confident-ai.com/docs/ai-governance/policies/gate-deployments-in-ci-cd)
- [Braintrust evaluation experiments and CI](https://www.braintrust.dev/docs/evaluate/run-evaluations)
- [Inspect AI](https://inspect.aisi.org.uk/)
- [NVIDIA Model Optimizer](https://github.com/NVIDIA/Model-Optimizer)
- [ONNX Runtime quantization](https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html)

## Removed from the technical bibliography

R10 and R20 were internal naming assertions, not external references. R11-R19
were a mixture of naming-collision notes and incompletely sourced product claims.
They no longer support the technical or market thesis. Brand clearance belongs in
a dated legal/namespace worksheet and must be rerun immediately before public
release; it must not be presented as a durable research bibliography.
