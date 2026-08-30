# Contributing to Merriv

Merriv is contract-first infrastructure in an external problem-validation phase.
Before proposing a large feature, first check whether a real release workflow in
the [external validation guide](docs/external-validation.md) demonstrates the
need. Then open an RFC that describes the user problem, compatibility impact,
evidence semantics, security boundary, and acceptance tests.

Participation is governed by the [Community Code of Conduct](CODE_OF_CONDUCT.md).

For code changes:

1. Install the locked development environment with
   `uv sync --frozen --extra dev --extra onnx`.
2. Add or update deterministic tests.
3. Keep unit tests offline and free of model downloads.
4. Run `uv run --frozen ruff check .`, `uv run --frozen mypy src`, and
   `uv run --frozen pytest`.
5. Do not add telemetry, remote execution, or untrusted-code loading by default.
6. Treat public schemas, report formats, and plugin contracts as compatibility
   boundaries.
7. Run Model Change Report conformance and cross-language identity checks for
   protocol changes.
8. Add migration and protocol-changelog entries for any breaking public change.

See [SUPPORT.md](SUPPORT.md) for issue routing,
[docs/external-validation.md](docs/external-validation.md) for workflow reviews,
[docs/protocol-governance.md](docs/protocol-governance.md) for Model Change Report
changes, and
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

## Bootstrap project stewardship

`@niansia` is the current bootstrap maintainer for the evidence kernel, releases,
and security. This is a single-maintainer risk, not a claim of mature governance.
Review authority should follow sustained public work and compatibility/security
judgment; breaking protocol changes need a public rationale and review window,
and two approvals once a second maintainer exists.

The project has no publicly verified external production adopter or independently
maintained Model Change Report implementation. Repository-owned Python, Node,
Rust, Polygraphy,
and MLflow references are conformance evidence only. An external-use claim must
link a real release, independent implementation, or reproduction with its exact
revision, role, evidence, date, and limitations; stars, downloads, plans, and
repository-owned dry runs do not qualify.

Routine reversible work uses pull-request review. Public schema, identity, gate,
trust-boundary, or protocol changes require a short decision record stating the
problem, alternatives tried, trade-offs, migration, and acceptance evidence.
Security reports continue to follow [SECURITY.md](SECURITY.md), including private
reporting and embargo handling.
