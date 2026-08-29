# RFC-0003: Evidence Graph and Claim Strength

- Decision status: Accepted
- Implementation status: Implemented for MCR 1.3
- Target: v0.1

## Motivation

An evaluation score without provenance is not release evidence. A gate verdict
without inspectable evidence cannot earn organizational trust.

## Decision

M2RIV models release analysis as a content-addressed evidence graph:

```text
ModelSnapshot -> Observation -> Metric/Diff -> Claim -> GateDecision -> MCR
```

Each derived claim links immutable evidence references and declares its strength:
descriptive, observed, statistical, or causal. Access level and limitations are
first-class. A reporter may simplify presentation, but cannot silently strengthen
a claim beyond its evidence.

This graph is the future basis for cache reuse, audit trails, redaction, report
signing, and portable Model Change Reports.
