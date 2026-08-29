# RFC 0008: Brand decision gate

- Decision status: Provisional
- Implementation status: Gate defined; owner clearance pending
- Deadline: before public v0.1 namespace publication

The dated engineering scan is recorded in
[`docs/brand-preliminary-audit.md`](../docs/brand-preliminary-audit.md). It does
not replace legal clearance or the owner decision required by this RFC.

## Decision

Keep `M2RIV` only as the pre-alpha working name. Stop claiming that a new engineer
will pronounce it correctly without explanation. No replacement name is adopted
until it passes stronger checks than the current name.

Before public v0.1, the maintainer must either confirm M2RIV or perform one
coordinated rename of the package, CLI, repository, schemas, content-ID namespace,
documentation, and examples. The gate requires:

1. ten unaided spoken-name tests with target users, recording pronunciation and
   spelling-back success;
2. exact and near-match checks across GitHub, PyPI, major package registries,
   search, model hubs, and relevant domains;
3. professional trademark review in intended markets;
4. a written comparison against at least three cleared alternatives;
5. confirmation that product renaming does not alter the protocol-owned
   `mcr:sha256:` namespace adopted by RFC 0015.

The protocol-namespace portion of this gate is complete. Product/package/CLI
branding still requires the owner clearance above.

Stars, public integrations, or a stable MCR consumer must not be accumulated under
a name that has not passed this gate. The current decision avoids replacing one
uncleared name with another invented during implementation.
