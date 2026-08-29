# RFC 0013: Authenticated cache envelopes and explicit evidence trust

- Decision status: Accepted
- Implementation status: Implemented for v0.1
- Contract impact: cache format v2; current MCRVerification 0.2

## Problem

The original cache envelope used public, unkeyed content fingerprints. That detected
accidental corruption but did not authenticate the writer: anyone able to modify the
cache could replace an observation, recompute every public digest, and turn a BLOCK
into a self-consistent PASS. The portable MCR verifier would then correctly validate
the forged bundle's internal identities while consumers could incorrectly interpret
`valid: true` as evidence provenance.

## Decision

Observation cache format v2 authenticates the complete envelope—format, cache-key
digest, and strict Observation—with HMAC-SHA-256. The HMAC key is domain-derived and is
never persisted. Every hit verifies the tag, cache key, snapshot, case, seed, retained
output digest, and kernel-owned observation content ID before returning the value.

With no configured key, each evaluator process generates a random key shared by its
cache instances. This makes the cache run-local and treats older or foreign entries as misses. Cross-process
or multi-worker reuse is opt-in through `M2RIV_CACHE_KEY`, which must contain at least
32 bytes of secret material. A deployment using a shared key must restrict read/write
access to both the key and cache; HMAC cannot defend against a process that has both.
Format-v1 entries are not migrated or trusted and therefore become cache misses.

The evidence kernel, not an adapter, creates every Observation ID from a versioned,
replay-stable projection of snapshot, case, seed, output digest, and retention mode.
Retry count, latency, timestamp, and traces remain run provenance rather than evidence
identity. The runner validates dispatch cardinality and recomputes identities before
any cache write.

MCRVerification 0.2 separately exposes:

- `integrity_valid`: all checks actually performed succeeded;
- `bundle_verification_complete`: every referenced local component was recognized
  and rehashed;
- `evidence_body_coverage` and `metric_recomputable`: retained body and replay
  scope without conflating them with bundle integrity;
- `trust_scope: self-consistency-only`; and
- `authenticity_verified: false`.

`m2riv mcr verify --strict` fails incomplete bundles. It still cannot authenticate a
producer because public content hashes are not signatures. Producer signing and
transparency anchoring remain separate future controls.

## Security consequences

Public-digest cache poisoning no longer works without the HMAC key. Default behavior
prefers a safe miss over untrusted reuse. The change does not protect a compromised
kernel process, an attacker who reads the shared key, or false observations created by
an authorized producer. Those require isolation, role separation, and signed evidence
roots as described in RFC-0004.
