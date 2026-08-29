# M2RIV Governance

M2RIV is contract-first infrastructure. Project authority follows demonstrated,
sustained responsibility for compatibility, evidence integrity, security, and the
health of contributors—not employer affiliation or code volume alone.

## Roles

- **Contributor:** opens issues, RFCs, documentation, tests, integrations, or code.
- **Reviewer:** has repeated contributions in an area and may approve changes in
  that area.
- **Maintainer:** shares responsibility for releases, cross-module architecture,
  contributor support, and incident response.
- **Release steward:** a maintainer assigned to one release; verifies schemas,
  compatibility notes, CI, artifacts, and security sign-off.

Reviewers and maintainers are nominated in a public issue by an existing
maintainer. The nomination should cite sustained work, review quality, security
judgment, and community conduct. With multiple maintainers, two approvals are
preferred; unresolved objections require a written rationale and another review
cycle. Emeritus status preserves credit without ongoing review obligations. The
current bootstrap roster and bus-factor statement are public in
[MAINTAINERS.md](MAINTAINERS.md).

## Decisions

Routine, reversible implementation work uses pull-request review. Changes to
public schemas, plugin/executor contracts, gate semantics, evidence identity,
security boundaries, or project scope require an RFC. RFCs must state the user
problem, alternatives, compatibility impact, threat model, migration, and
acceptance tests.

Breaking MCR changes follow [protocol governance](docs/protocol-governance.md),
including a public review window, exact new envelope version, migration guide,
negative fixtures, protocol changelog, and cross-language vectors. Security
embargoes are the only exception to public pre-merge discussion.

Consensus is preferred. If consensus cannot be reached, maintainers document the
competing positions and choose the smallest reversible decision that preserves
security and compatibility. A release steward may block a release for an
unresolved evidence-integrity or credential-safety issue.

When only one maintainer exists, that maintainer may merge after the documented
review window but must record unresolved objections and why the decision is
reversible or necessary. Once two maintainers exist, breaking protocol changes
require two approvals. A maintainer with a direct employer or commercial conflict
discloses it and does not act as the sole deciding reviewer.

## Compatibility

Generated JSON Schemas, MCR semantics, cache identity inputs, exit codes, and SDK
protocols are compatibility surfaces. Additive optional fields may use a minor
schema/API version. Required or semantic changes require a major version and an
explicit migration path.

Pre-1.0 does not mean silent breakage. Every supported exact protocol version has
normative schemas, a changelog entry, compatibility matrix, conformance fixtures,
and a bounded migration or explicit rejection path.

## Continuity and succession

Maintainers should keep release, security, and protocol processes reproducible
from repository evidence rather than private memory. If the project lead is
inactive for 60 days and an urgent compatibility or security action is required,
two active reviewers may publish a succession proposal with evidence of attempted
contact and a seven-day public review. No successor inherits private credentials;
repository and package ownership must be transferred through their native audited
controls.

## Security

Security reports follow [SECURITY.md](SECURITY.md). Credentials, raw private model
outputs, and exploit details must not be posted in public issues. A security fix
may use a private embargo, but the eventual advisory should explain the affected
invariant and regression coverage without disclosing user secrets.

## Vendor neutrality

No cloud, model provider, registry, scheduler, or employer receives privileged
status in the evidence kernel. Vendor integrations live behind public contracts
and must remain replaceable.
