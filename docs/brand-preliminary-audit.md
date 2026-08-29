# M2RIV preliminary name audit

Checked: 2026-08-29

This is an engineering namespace scan, not legal or trademark clearance. Exact
`m2riv` lookups returned no project/user record at the time of checking in:

- [PyPI project endpoint](https://pypi.org/project/m2riv/) (404)
- [GitHub account endpoint](https://github.com/M2RIV) (404)
- npm registry package endpoint for `m2riv` (404 via the registry API)

General web searches for the exact uppercase/lowercase string did not find a
software product collision; they did find unrelated catalog notation, usernames,
and text fragments. Search-engine queries against public USPTO, EUIPO, and Canadian
trademark pages returned no exact result, but that is not an authoritative
clearance search and does not cover confusingly similar names, company registries,
domains, common-law use, or every jurisdiction.

## Decision still required

Before public v0.1, the owner must either:

1. obtain an appropriate professional clearance and reserve the coordinated
   GitHub/PyPI/domain namespaces; or
2. choose a replacement and execute the migration in RFC-0008 before third-party
   MCR producers depend on `m2riv:sha256:`.

The release workflow is deliberately gated by repository variable
`M2RIV_BRAND_CLEARED=true`; this file alone is not authorization to set it.
