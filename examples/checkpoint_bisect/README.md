# Locate the first bad checkpoint

Each JSONL row is an ordered checkpoint and an already computed release status.
The example has a monotonic `PASS` to `BLOCK` transition.

```console
m2riv bisect examples/checkpoint_bisect/checkpoints.jsonl --mode monotonic
```

The command exits `2` and reports `checkpoint-004` as the first failing revision.
Use `sparse_audit` when you only want bounded sampling, or `linear_audit` when every
checkpoint can be evaluated and non-monotonic reversals must be found.
