# MCR compatibility matrix

Last verified: 2026-08-29. “Verified” means the committed conformance command is
run in CI or the stated fixture is deterministically regenerated. It does not
mean a vendor has endorsed MCR.

| Implementation | Role | MCR | Profile | Status |
|---|---|---:|---|---|
| M2RIV CLI | producer + verifier | 1.3.0 | full local bundle | verified in CI |
| `examples/independent_producer` | producer, no M2RIV import | 1.3.0 | full identity | verified in CI |
| `integrations/polygraphy_mcr` | producer adapter | 1.3.0 | normalized translation | verified in CI; live Polygraphy requires NVIDIA environment |
| `integrations/mlflow_mcr` | consumer, no M2RIV import | 1.3.0 | PASS/WARN/BLOCK receipt | verified in CI; live MLflow logging is environment-owned |
| Node identity verifier | identity consumer | RFC 0012 | golden vectors | verified in CI |

## Capability labels

- **contract**: parses and preserves the exact schema;
- **identity**: recomputes normative content IDs;
- **decision**: preserves PASS/WARN/BLOCK/ERROR and fail-closed authorization;
- **complete bundle**: rehashes all local required bodies;
- **live integration**: executed against the named external runtime.

An integration must not advertise “live” from a dry run, documentation build, or
normalized fixture. The NVIDIA vertical records this distinction explicitly.
