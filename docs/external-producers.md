# External producer and consumer boundary

The Model Change Report format is cross-language. The Python `ModelAdapter`,
`ExecutionBackend`, and metric protocols are implementation APIs for the Merriv
reference tool; they are not the ecosystem extension ABI.

An external C++, Rust, Go, Java, Python, or internal-system producer has three
stable boundaries:

1. emit JSON conforming to the public Model Change Report schemas;
2. implement RFC 0012 content identity and pass the fixed producer conformance
   suite, including must-reject fixtures; or
3. retain native output and translate it through a file/process importer before
   report construction.

No external producer needs to import `merriv` or implement a Python Protocol.

## Smallest working path

For a tool that already has paired case outputs:

```console
merriv compare baseline.jsonl candidate.jsonl \
  --suite suite.jsonl \
  --policy policy.yaml \
  --output runs/release
```

The three JSONL files are the language-neutral process boundary. Each row carries
a stable `case_id`; the suite holds input/expected/slices and the recorded files
hold the baseline or candidate output for the same case.

For retained Polygraphy results:

```console
merriv import polygraphy run-results.json \
  --baseline-runner onnxrt-runner \
  --candidate-runner trt-runner \
  --policy policy.yaml \
  --output runs/polygraphy-mcr
```

`--format normalized` accepts the documented small JSON interchange used by CI.
That path proves wiring only and is labeled as non-live evidence in CLI output.
Native `RunResults` remain the authoritative Polygraphy input and require the
optional Polygraphy package in the caller's environment.

## Independent Model Change Report implementation

An implementation is independent only when it is maintained outside this
repository and does not call Merriv to construct or interpret the result being
claimed. To establish interoperability it should publish:

- implementation and schema version;
- producer or consumer conformance receipt;
- supported identity tier;
- exact pass and must-reject fixtures;
- ownership repository and maintainer; and
- live-runtime evidence separately from normalized or dry-run fixtures.

Repository-owned Python, Node, Rust, Polygraphy, and MLflow references are useful
tests but are not counted as external adoption.

## Transport

Plain JSON bundles remain the baseline contract. in-toto Statements add a
standard attestation layer, and OCI 1.1 provides a registry transport/referrer
surface. See [supply-chain interoperability](supply-chain-interop.md).

Protobuf or a long-running plugin RPC protocol is intentionally not normative at
MCR 0.4. Adding one before a real external producer demonstrates a need would
create a second compatibility surface without adoption evidence.
