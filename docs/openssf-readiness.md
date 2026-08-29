# OpenSSF readiness record

This is an evidence checklist, not an OpenSSF badge claim.

## Repository controls implemented in source

- Apache-2.0 license, Code of Conduct, contribution, governance, support,
  maintainer, security, and adopter policies;
- private-vulnerability-reporting instructions and bounded security response
  targets;
- SHA-pinned GitHub Actions, read-only default permissions, isolated release OIDC,
  checksums, SPDX SBOM, and provenance attestations;
- Dependabot, dependency audit, dependency review, CodeQL, and OpenSSF Scorecard
  workflows;
- deterministic tests, coverage gate, strict typing, lint, schema drift,
  cross-language identity vectors, conformance, and adversarial tests;
- protected compatibility surfaces with RFC, migration, and protocol changelog
  requirements.

## Owner/account evidence still required before public v0.1

- verify the default-branch ruleset and required checks after all new workflows
  have completed once;
- verify private vulnerability reporting and security-alert notifications with
  the active owner account;
- configure PyPI Trusted Publishing and protected `pypi` environment only after
  brand clearance;
- capture the first successful public Scorecard and CodeQL run links;
- obtain a second human reviewer/maintainer for bus-factor reduction;
- perform professional brand/trademark clearance.

OpenSSF Scorecard findings are treated as prioritized evidence, not a score to
game. Any accepted exception must state the threat, compensating control, owner,
and review date.
