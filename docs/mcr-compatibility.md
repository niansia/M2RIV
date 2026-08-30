# MCR compatibility matrix

Last verified: 2026-08-29. “Verified” means the committed conformance command is
run in CI or the stated fixture is deterministically regenerated. It does not
mean a vendor has endorsed MCR.

| Implementation | Role | MCR | Profile | Status |
|---|---|---:|---|---|
| Merriv CLI | producer + verifier | 0.4.0 | strict full bundle + target root | verified in CI |
| `examples/independent_producer` | producer, no Merriv import | 0.4.0 | full identity | verified in CI |
| `reference/mcr-reference-rust` | producer + identity verifier | 0.4.0 | typed vectors + report/evidence/run | verified in CI |
| `integrations/polygraphy_mcr` | producer adapter | 0.4.0 | native comparator translation | normalized CI fixture; live NVIDIA evidence retained separately |
| `integrations/mlflow_mcr` | consumer, no Merriv import | 0.4.0 | five-state receipt | verified in CI; live MLflow logging is environment-owned |
| Node identity verifier | identity consumer | RFC 0012 | typed golden vectors | verified in CI |

## Capability labels

- **contract**: parses and preserves the exact schema;
- **identity**: recomputes normative content IDs;
- **decision**: preserves PASS/WARN/INSUFFICIENT_POWER/BLOCK/ERROR and the
  fail-closed evaluation-policy disposition without claiming deployment authority;
- **complete bundle**: rehashes every declared local required body;
- **target root**: detects changed, missing, or unlisted retained target files;
- **live integration**: executed against the named external runtime.

An integration must not advertise “live” from a dry run, documentation build, or
normalized fixture. Repository-owned implementations and first-party GPU runs do
not count as external adoption.

## MCR 0.4 freeze

MCR 0.4.0 is the external-review baseline. The envelope field set, canonical
identity preimages, and field meanings are not edited in place. A required-field,
semantic, or hashing change requires a new envelope version plus migration
vectors. Additive verifier output, import commands, and transport helpers do not
change the MCR envelope.
