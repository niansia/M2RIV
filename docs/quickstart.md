# Quickstart

This guide runs a complete release evaluation without downloading a model or calling a
remote service. The fixture is intentionally bad so that a correct run returns
`BLOCK`.

## Run without cloning

```console
uvx --python 3.13 --from git+https://github.com/niansia/Merriv.git merriv demo --output runs/quickstart
```

Python 3.11, 3.12, and 3.13 are supported. The base install contains no ONNX,
GPU, MLflow, or Polygraphy dependency. Once the first tagged PyPI release is
published, the equivalent command is
`uvx --from m2riv merriv demo --output runs/quickstart`.

## Run the repository fixture

The following variant requires a repository checkout because it uses editable
JSONL and YAML fixtures:

```console
merriv compare \
  examples/recorded_compare/baseline.jsonl \
  examples/recorded_compare/candidate.jsonl \
  --suite examples/recorded_compare/suite.jsonl \
  --policy examples/recorded_compare/policy.yaml \
  --slice-key frequency \
  --output runs/quickstart
```

Expected decision:

```text
EVALUATION DECISION: BLOCK
EVALUATION POLICY SATISFIED: false
DEPLOYMENT AUTHORIZATION: NOT EVALUATED (consumer-side)
```

Metric values remain in the generated Model Change Report rather than being
duplicated here.
The exact console formatting may evolve; the decision, evidence identity, and
bounded output contracts are covered by tests and schemas.

## Verify the bundle

```console
merriv mcr verify runs/quickstart --strict
```

Strict verification rehashes every recognized local component. It checks bundle
integrity and declared conformance, not producer identity or model safety.

## Generated files

| File | Purpose |
|---|---|
| `mcr-report.json` | Portable Model Change Report |
| `evidence-manifest.json` | Deduplicated observation and evidence references |
| `release-plan.json` | Content-addressed policy and execution preflight |
| `summary.md` | Human-readable decision summary |
| `junit.xml` | CI test-report integration |
| `results.sarif` | Code-scanning annotation integration |

Generated runs belong in `runs/`, which is ignored by Git. Only small normative
fixtures and reproducible examples are retained in the repository.

## Exit codes

| Code | Meaning |
|---:|---|
| `0` | PASS |
| `2` | BLOCK |
| `3` | Invalid, incomplete, or unsafe evidence |
| `4` | WARN or INSUFFICIENT_POWER |

WARN is fail-closed by default. INSUFFICIENT_POWER is always fail-closed, even
when a policy explicitly allows WARN.

## Next examples

- [Real historical llama.cpp #22544 replay](../examples/historical_llamacpp_22544/README.md)
- [CPU ONNX quantization regression](../examples/onnx_quantization/README.md)
- [ONNX opset control](../examples/onnx_opset_upgrade/README.md)
- [NVIDIA ModelOpt/TensorRT vertical](../examples/nvidia_tensorrt_vertical/README.md)
- [OpenAI-compatible endpoint comparison](../examples/api_compare/README.md)
- [Independent Model Change Report producer](../examples/independent_producer/README.md)

## Development environment

Install the locked development surface and run the standard checks:

```console
uv sync --frozen --extra dev --extra onnx
uv run --frozen ruff check .
uv run --frozen mypy src
uv run --frozen pytest
```

See [CONTRIBUTING.md](../CONTRIBUTING.md) for change, test, schema, and RFC rules.
