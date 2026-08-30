# Plugin SDK and execution contracts

Merriv exposes three narrow extension boundaries:

1. `ModelAdapter` resolves a model snapshot and produces observations.
2. `PairedMetric` maps paired observations to numeric baseline/candidate samples.
3. `ExecutionBackend` decides where an adapter runs.

Adapters and executors cannot issue release verdicts. Metrics cannot mutate
observations or bypass paired statistics. The evidence kernel owns pairing,
identity validation, uncertainty, gate semantics, and report generation.

## Explicit registration

`PluginRegistry` accepts already-instantiated metrics together with a strict
`PluginManifest`. Registration checks API version, identifiers, units, direction,
duplicate ownership, capabilities, and capacity limits. It never discovers or
imports Python entry points automatically.

```python
registry.register_metric(manifest, metric)
plan = compile_release_plan(
    policy=policy,
    cases=cases,
    metrics=registry.metrics(),
    slice_keys=("risk",),
    metric_plugins=registry.metric_plugin_records(),
)
```

Plugin configuration must be represented by a non-secret fingerprint. Credentials,
raw prompts, endpoint response bodies, and secret hashes do not belong in a
manifest.

Executors can be registered the same way. The manifest config fingerprint must
equal the `ExecutorDescriptor` config fingerprint, and descriptor capabilities
must be a subset of the manifest declaration. Mutation after registration is an
error.

Adapters may also be registered under a host-chosen ID. Their manifest config
fingerprint must match the resolved `ModelSnapshot`, and their declared
capabilities must cover the adapter contract. Snapshot or capability mutation after
registration is rejected.

## Execution backends

An executor exposes an `ExecutorDescriptor` and an `execute` method. Its config
fingerprint participates in every observation cache key. Switching from local to
a remote worker, another container image, or a different scheduling configuration
therefore cannot silently reuse incompatible observations.

The runner independently validates returned snapshot IDs, case IDs, output
digests, duplicates, missing results, and unexpected results. Executor and plugin
exceptions are converted to secret-free failures. The built-in `LocalExecutor`
runs only code the host already trusted and imported.

## Compiled release plans

`compile_release_plan` runs before inference. It binds every policy rule to an
available metric and observed slice, verifies optimization direction, applies
cardinality limits, fingerprints the suite/policy/plugin declarations plus runtime
and statistical settings, and emits a content-addressed `CompiledReleasePlan`.

Use the CLI for a zero-inference preflight:

```console
m2riv plan --suite suite.jsonl --policy policy.yaml --slice-key risk
```

The plan ID is linked from the final MCR. The MCR also records the actual executor
identity and dispatched/returned counts for baseline and candidate.

## Trust boundary

The SDK is not a Python sandbox. Do not import untrusted plugin packages into a
privileged CI process. Use signed/reviewed packages, pinned hashes, a restricted
worker, network deny-by-default, filesystem isolation, and an external secret
manager. Merriv validates outputs and provenance but cannot undo arbitrary code
execution already granted by the host.
