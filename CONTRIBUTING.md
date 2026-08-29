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
6. Run MCR conformance and cross-language identity checks for protocol changes.
7. Add migration and protocol-changelog entries for any breaking public change.

See [SUPPORT.md](SUPPORT.md) for issue routing,
[docs/protocol-governance.md](docs/protocol-governance.md) for MCR changes, and
[docs/external-reproduction-guide.md](docs/external-reproduction-guide.md) for
corpus or GPU evidence.

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
