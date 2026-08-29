# RFC-0002: Core Contracts and Content Identity

Status: Draft
Target: v0.1
## Decision

Public contracts are strict, immutable Pydantic models with a semantic schema
version. Unknown fields fail validation. Cross-language JSON Schemas are generated
from the same source.

A `ModelSnapshot` identifies execution-relevant model state, not a filename or
registry tag. Local identity is derived from artifact contents and an execution
configuration fingerprint. Paths remain provenance but do not participate in the
identity. Hashes use domain separation so an identical byte string cannot be
mistaken for a different M2RIV object type.

## Compatibility

- Additive optional fields may appear in a minor schema release.
- Required-field or semantic changes require a major schema release.
- Producers must emit `schema_version`; consumers must reject unsupported majors.
