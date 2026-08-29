# Content-identity conformance

`golden-vectors.json` freezes representative canonical JSON bytes and SHA-256
fingerprints for the M2RIV v1 identity algorithm. The Python and Node verifiers
use only their standard libraries and do not import M2RIV.

```console
python examples/content_identity/verify_golden.py
node examples/content_identity/verify_golden.mjs
```

The normative rules, including the portable numeric profile and domain
separation, are in [RFC 0012](../../rfcs/0012-content-identity-canonicalization.md).
