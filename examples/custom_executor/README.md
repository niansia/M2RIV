# Custom execution backend
`TaggedLocalExecutor` demonstrates the exact boundary a remote execution plugin
implements. Its non-secret worker-pool configuration participates in both the
manifest and executor descriptor fingerprint.

```python
registry = PluginRegistry()
executor = register(registry, worker_pool="gpu-a100-prod")

result = compare_release(
    ...,
    baseline_executor=executor,
    candidate_executor=executor,
)
```

The example still executes in-process. A distributed implementation replaces only
`execute`; pairing, cache validation, metrics, statistics, gates, and reports stay
inside the Merriv kernel. Never place cluster credentials in the manifest or
descriptor.
