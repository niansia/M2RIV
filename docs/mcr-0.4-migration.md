# Migrating from legacy MCR 1.3 bundles to MCR 0.4

MCR 0.4 is an intentional pre-1.0 breaking correction. Existing 1.3 bundles are
historical evidence and remain readable as JSON, but the current verifier rejects
them rather than guessing new identity semantics. Regenerate evidence from the
original retained inputs whenever possible.

## Required changes

| Legacy surface | MCR 0.4 surface |
|---|---|
| `m2riv-report.json` | `mcr-report.json` |
| `schema_version: 1.3.0` | `schema_version: 0.4.0` |
| `m2riv:sha256:<digest>` | `mcr:sha256:<digest>` |
| `m2riv:<namespace>:v1` hash domain | `mcr:<namespace>:v1` |
| `id` treated as evidence identity | new `evidence_id` for stable evidence |
| verdict omitted from stable `id` | report `id` includes the complete decision |
| one completeness boolean | bundle completeness, body coverage, and recomputability |
| PASS/WARN/BLOCK fixtures | PASS/WARN/INSUFFICIENT_POWER/BLOCK/ERROR plus negative fixtures |
| Legacy project-branded manifest media type | `application/vnd.model-change-report.evidence-manifest+json` |

## Migration procedure

1. Preserve the original bundle read-only and record its SHA-256 externally.
2. Re-run the producer using the same artifact bytes, suite, policy, seed, and
   runtime whenever those inputs remain available.
3. Emit `evidence_id`, decision-bound `id`, and exact `run_id` using RFC 0012 and
   RFC 0015. Do not string-replace old IDs.
4. Rename the canonical report file and update manifest media types/references.
5. Preserve tool-native output and bind artifact/build provenance where the report
   makes external comparator or target-build claims.
6. Run `merriv mcr verify BUNDLE --strict` and the MCR 0.4 producer suite.
7. For a target archive, create and verify `target-evidence-manifest.json` only
   after the retained tree is complete.

If original observations are unavailable, mark them unavailable and accept that
`metric_recomputable` will be false. Do not manufacture bodies merely to obtain a
complete-looking verification result.
