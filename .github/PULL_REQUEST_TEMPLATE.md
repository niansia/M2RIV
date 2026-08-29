## Problem and outcome
<!-- What user/release-engineering problem does this solve? -->

## Evidence and verification

- [ ] Deterministic tests added or updated
- [ ] `uv run --frozen ruff check .` passes
- [ ] `uv run --frozen mypy src` passes
- [ ] `uv run --frozen pytest` passes
- [ ] Public schema output checked when contracts changed

## Compatibility and security

- [ ] No public contract or behavior change
- [ ] Or: RFC/migration notes linked below
- [ ] Secrets, raw private outputs, and credential hashes are absent from identity,
      cache, reports, logs, and exceptions
- [ ] Resource/cost limits and fail-closed behavior were considered

## Plugin/executor changes

- [ ] Not applicable
- [ ] Manifest/API version and non-secret config identity documented
- [ ] Capabilities and mutation behavior tested
- [ ] Trust/isolation boundary documented
