# Public release checklist

Repository automation is ready to build, verify, attest, and—only after the
following owner-side gates—publish through PyPI Trusted Publishing. A green local
test suite does not satisfy these account-level controls.

## One-time owner gates

- Complete the brand decision in RFC-0008. The preliminary scan is evidence, not
  legal clearance.
- Reserve or create the chosen PyPI project and configure its GitHub Trusted
  Publisher for this repository, workflow filename `release.yml`, environment
  `pypi`.
- Create the protected GitHub environment `pypi` with at least one required human
  reviewer and no long-lived package token.
- Set repository variable `M2RIV_BRAND_CLEARED=true` only after the chosen package,
  repository, content-ID namespace, action reference, and documentation name agree.
- Enable GitHub private vulnerability reporting; subscribe at least two monitored
  maintainer accounts to security alerts and test the notification path.
- Protect tag creation and require review for changes to `release.yml` and
  `.github/CODEOWNERS`.

PyPI identifies a Trusted Publisher by repository owner, repository, workflow,
and optionally environment. The publish job has only `contents: read` and
`id-token: write`, is isolated from the build job, uses the protected `pypi`
environment, and cannot run unless both a `v*` tag and the brand-clearance variable
are present. See the [PyPI setup instructions](https://docs.pypi.org/trusted-publishers/adding-a-publisher/)
and [security model](https://docs.pypi.org/trusted-publishers/security-model/).

## Per-release checks

1. Confirm the version and changelog, then rerun lint, typing, tests, schema drift,
   wheel build/install, both ONNX platform jobs, the composite-action smoke job,
   both language identity vectors, and all conformance fixtures.
2. Review every change to the release workflow and immutable action SHAs.
   Regenerate `action-requirements.lock` from the committed `uv.lock` whenever a
   core dependency changes and review the resulting hashes.
3. Create the signed/protected `v*` tag from the reviewed commit.
4. Approve the `pypi` environment only after the build job produces wheel, source
   distribution, SHA256SUMS, SPDX SBOM, and GitHub provenance.
5. Verify the published project metadata, attestations, hashes, installation, and
   `m2riv --help` from a clean environment.
6. Confirm private vulnerability-report notifications remain monitored.
