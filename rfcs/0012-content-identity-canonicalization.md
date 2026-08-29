# RFC 0012: Content-identity canonicalization

- Decision status: Accepted
- Implementation status: Implemented for identity algorithm v1
- Contract impact: MCR content IDs and every `m2riv:sha256:` reference

## Problem

MCR identities are intended to be recomputable by producers that do not import
M2RIV. JSON Schema describes the data shape, but it does not define byte-level
canonicalization, domain separation, or the treatment of typed values before
hashing. Without those rules, two conforming implementations can hash the same
semantic evidence to different IDs.

## Decision

Identity algorithm `v1` is frozen as follows.

1. Convert typed contract values to a JSON-compatible tree. Pydantic models are
   dumped in Python mode with explicit null/default fields. String enums become
   their values, paths use POSIX separators, timezone-aware datetimes use ISO 8601
   `isoformat()`, and tuples become arrays. Sets in the portable producer profile
   contain only safe-identifier strings and are sorted by Unicode code point.
   The Python helper retains legacy deterministic handling for other set element
   types, but those values are outside the cross-language v1 profile and producers
   must represent them as explicitly ordered arrays. Naive datetimes, non-string
   object keys, NaN, and infinity fail.
2. Serialize the tree as UTF-8 JSON with no byte-order mark or insignificant
   whitespace. Object keys are sorted by Unicode code point, strings are not
   Unicode-normalized and are emitted without ASCII-only escaping, arrays retain
   order, and null is `null`. Slash escaping is not added.
3. Booleans are not numbers. Integers use base-10 without leading zeroes. Finite
   binary64 floats use Python's shortest round-trippable spelling; negative zero
   is `-0.0`. Cross-language v1 producers must retain the schema's integer/float
   distinction. The portable generic-JSON profile is limited to integers and
   non-integral finite binary64 values whose shortest spelling agrees with the
   published vectors. Integral-valued floats require a schema-aware formatter.
4. The fingerprint input is the UTF-8 domain separator
   `m2riv:<namespace>:v1`, one NUL byte, then the canonical JSON bytes. Namespace
   strings are non-empty and contain no NUL. The result is lowercase SHA-256 hex.
   Contract IDs prefix that digest with `m2riv:sha256:`.

Schema-version fields participate whenever the identity payload includes them.
Unknown fields are rejected by public contracts; the generic fingerprint helper
hashes every field it is explicitly given. Wire spelling such as a datetime `Z`
is parsed into its typed contract value before identity is recomputed, so UTC is
canonicalized to the typed `+00:00` form.

## Conformance

[`examples/content_identity/golden-vectors.json`](../examples/content_identity/golden-vectors.json)
contains canonical bytes and digests. Its conformance-only typed-value notation
uses exact IEEE-754 hexadecimal bits for binary64, base-10 strings for integers,
and explicit tags for datetime, path, and set inputs. This prevents a generic
JSON parser from erasing `1` versus `1.0` before the algorithm is tested. The
notation is not part of the MCR wire format.

Independent Python, Node, and Rust implementations verify 20 typed vectors plus
1,024 deterministic finite-binary64 spelling vectors in CI,
including negative zero, smallest subnormal, minimum normal, maximum finite,
Python fixed/scientific boundaries, hard round-trip values, Unicode scalar
ordering, emoji and combining characters, typed UTC/offset datetime, portable
paths, portable string sets, explicit defaults/nulls, escaping, and large
integers. Full MCR fixtures add contract-level vectors for report, run, manifest,
evidence-set, release-plan, artifact-diff, and numerical-diff namespaces.

The Rust reference additionally produces a minimal MCR that the Python verifier
accepts and recomputes IDs for a Python-produced MCR. This closes implementation
interoperability for the exercised MCR 1.3 profile; it does not prove that every
possible binary64 spelling is portable or remove the schema-aware formatter
requirement.

## Compatibility

This RFC documents and freezes the existing v1 algorithm; it does not change
current IDs. A future canonicalization change must use a new domain version and
publish migration vectors. RFC 8785 is not adopted retroactively because its
number and string rules would change existing content addresses.

Before an MCR 2.0/public identity v2 freeze, maintainers MUST compare this v1
cost against a type-explicit or non-floating identity profile. Identity-bearing
thresholds and measurements SHOULD prefer decimal strings or scaled integers
when their domain has an exact decimal unit. Arbitrary binary64 remains allowed
in v1 only where the schema supplies the type needed by the formatter.
