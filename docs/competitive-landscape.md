# Competitive boundary

Last verified: 2026-08-29. This page deliberately names adjacent projects. Merriv
does not claim to have invented model evaluation, CI regression tests, or release
gates.

## Application and agent evaluation

| Project | Verified existing surface | Boundary with Merriv |
|---|---|---|
| [MLflow model evaluation and validation](https://mlflow.org/docs/latest/ml/evaluation) | Candidate and baseline evaluation plus `threshold`, `min_absolute_change`, and `min_relative_change` validation through `validate_evaluation_results()`. | MLflow is an experiment/model lifecycle platform and already gates metrics. Merriv does not duplicate that claim; it offers a vendor-neutral artifact/change evidence envelope that MLflow can consume. |
| [Promptfoo](https://www.promptfoo.dev/blog/promptfoo-joining-openai/) | Open-source AI application eval, red teaming, static scanning, and CI workflows; announced its agreement to be acquired by OpenAI on 2026-03-09. | Prompt/application/agent security is its center. Merriv focuses on deployable artifact and compiler/runtime build provenance, paired artifact regressions, and build-sequence localization. |
| [DeepEval](https://deepeval.com/docs/introduction) | Pytest-style LLM application evaluation with built-in metrics for agents, RAG, safety, tools, conversations, and multimodal workflows. | DeepEval metrics may feed Merriv through an importer; Merriv does not try to replace its evaluator catalog. |
| [Confident AI](https://www.confident-ai.com/docs/ai-governance/policies/gate-deployments-in-ci-cd) | Governance policies can block deployments in CI through `deepeval gate`. | Merriv's distinct object is a baseline/candidate artifact pair and its content-addressed, uncertainty-aware change evidence. |
| [Braintrust](https://www.braintrust.dev/docs/evaluate/run-evaluations) | Immutable evaluation experiments, comparison over time, CI/CD integration, custom scorers, and production feedback. | Braintrust is an application-evaluation platform; Merriv remains local-first and treats deployment artifacts, executors, and portable Model Change Reports as neutral contracts. |
| [Inspect AI](https://inspect.aisi.org.uk/) | UK AI Security Institute framework for LLM evaluation tasks, datasets, solvers, scorers, agents, tools, sandboxes, and extensions. | Inspect suites can become evidence inputs. Merriv owns neither the benchmark zoo nor the LLM task runner. |

## Model transformation and deployment

| Project | Verified existing surface | Boundary with Merriv |
|---|---|---|
| [NVIDIA Polygraphy](https://docs.nvidia.com/deeplearning/tensorrt/latest/_static/polygraphy/comparator/toc.html) | Runs and compares backend outputs, persists `RunResults`, exposes per-output comparison results, and supports TensorRT/ONNX Runtime debugging. | Polygraphy should remain the NVIDIA-side numerical/backend oracle. Merriv converts retained results into an evaluation-policy result, portable Model Change Report, and ordered-build localization for a downstream promotion controller. |
| [NVIDIA Model Optimizer](https://github.com/NVIDIA/Model-Optimizer) | Quantization, distillation, pruning, sparsity, NAS, speculative decoding, and export to deployment runtimes. | ModelOpt makes optimized artifacts. Merriv checks whether an artifact build should replace its baseline and where a build regression began. |
| [TensorRT-Model-Connect validation](https://nvidia.github.io/TensorRT-Model-Connect/user-guides/validate-benchmark/) | Separates parser/unit, exact-model E2E, target compatibility, performance, and quality evidence; requires exact revision/config and reproducible hardware/software cohort. | This validates model-owned TensorRT integration contracts. Merriv targets portable cross-tool evidence semantics and does not treat a skipped GPU preflight as target evidence. |
| [ONNX Runtime quantization](https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html) | Dynamic/static INT8 quantization, QDQ/QOperator formats, calibration, preprocessing, and quantization debugging. | ONNX Runtime makes and executes quantized graphs. Merriv records semantic artifact changes, paired behavioral/system evidence, policy decisions, and bisect results. |
| [ModelDiff](https://github.com/MadryLab/modeldiff) | Fine-grained comparison of supervised learning algorithms using data attribution and distinguishing directions. | ModelDiff studies learning algorithms. Merriv is operational release evidence over concrete deployable builds. |
| [Vauban](https://github.com/teilomillet/vauban) | Behavioral change reports for language-model transformations, including access-aware claims. | Vauban is the closest behavioral-diff neighbor. Merriv narrows its primary wedge to artifact/compiler/runtime release gating across model families. |

## Positioning rule

Do not say “existing tools only show scores” or “nobody gates model releases.” Say:

> Application-evaluation tools test prompts, agents, RAG systems, and model
> behavior. Optimization and compiler tools produce deployment artifacts. Merriv
> connects the second event to release engineering: semantic artifact diff,
> paired confidence-interval evidence, policy-as-code, and regression localization
> across an ordered artifact/build sequence.

This is a boundary hypothesis, not a claim of market exclusivity. It should be
revisited whenever an adjacent project adds deployment-artifact provenance,
paired statistical gates, or build-sequence localization.

## When to use which tool

| Need | Start with | How Merriv fits |
|---|---|---|
| Prompt, RAG, agent, safety, or LLM application evaluation | Promptfoo, DeepEval/Confident AI, Braintrust, or Inspect AI | Import their retained results as external evidence only when a deployment release needs a portable change record. |
| Candidate/baseline experiment metrics and model lifecycle tracking | MLflow | Consume a verified Model Change Report in an MLflow run; do not claim Merriv invented threshold validation. |
| TensorRT vs ONNX Runtime output/layer debugging | Polygraphy | Preserve Polygraphy as the raw comparison oracle, then attach evaluation policy, Model Change Report, and bisect semantics; deployment authorization remains downstream. |
| Quantization or optimized artifact generation | ModelOpt or ONNX Runtime | Treat the tool output as the candidate build and retain its exact configuration/provenance. |
| Exact TensorRT model integration or target qualification | TensorRT-Model-Connect model-owned validation | Use its exact E2E/target evidence; Merriv may package that evidence for a cross-tool release decision. |
| Cross-tool promotion, audit, or CI handoff for an exact artifact change | Model Change Report | Produce or consume the vendor-neutral evidence envelope; the Merriv CLI is optional. |
