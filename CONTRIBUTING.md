# Contributing to M2RIV

M2RIV is contract-first infrastructure. Before proposing a large feature, open an
RFC that describes the user problem, compatibility impact, evidence semantics,
security boundary, and acceptance tests.

Participation is governed by the [Community Code of Conduct](CODE_OF_CONDUCT.md).

For code changes:

1. Add or update deterministic tests.
2. Keep unit tests offline and free of model downloads.
3. Run `ruff check .`, `mypy src`, and `pytest`.
4. Do not add telemetry, remote execution, or untrusted-code loading by default.
5. Treat public schemas, report formats, and plugin contracts as compatibility
   boundaries.

Plugin contributions must also document their trust boundary, non-secret config
identity, capabilities, resource limits, failure semantics, and which evidence
fields they produce. Plugins must not auto-register on import or emit release
verdicts outside the gate evaluator.

Artifact parser or runtime-adapter contributions must additionally document:

- whether parsing loads external files or executes custom/native code;
- byte, node, tensor, output, and recursion/cardinality limits;
- the exact fields that enter snapshot/cache identity;
- malformed-artifact and secret-canary tests;
- the isolation recommendation for hostile artifacts.
