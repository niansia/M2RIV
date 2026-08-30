# Merriv naming decision

Decision date: 2026-08-30

The public project and reference-implementation name is **Merriv**, pronounced
**“MEH-riv”** as one two-syllable word.

## Public naming rule

- Say and write **Merriv** in prose, talks, diagrams, CI labels, and user-facing
  output.
- Say and write **Model Change Report** in public prose. Use `MCR` only where it
  is a technical identifier: schema/version names, class names, the `mcr:` wire
  namespace, filenames, or the `mcr` CLI group.
- Do not present Merriv and the report format as competing brands. Merriv is the
  tool; Model Change Report is the portable evidence object it produces and
  consumes.

## Stable technical identifiers

The Python distribution and import module remain `m2riv`, preserving the clean
PyPI namespace and avoiding a brand-only wire migration. The primary executable
is `merriv`; `m2riv` remains an install-time compatibility alias. Existing
`m2riv.*` plugin/executor identifiers, `mcr:` content IDs, JSON field names,
filenames, and identity hash domains do not change because of this naming
decision.

The canonical GitHub repository is `github.com/niansia/Merriv`. GitHub redirects
the pre-rename `niansia/M2RIV` locator, but public documentation and package
metadata use the canonical Merriv URL.

## Distribution

The PyPI project remains `m2riv`; the distribution name is a stable technical
identifier rather than a second public brand. Before the first published release,
installation examples use the Git repository explicitly:

```console
uvx --from git+https://github.com/niansia/Merriv.git merriv --help
```

After publication, the unambiguous form is:

```console
uvx --from m2riv merriv --help
```

## Clearance boundary

General web and package-index searches found no software project occupying the
exact `Merriv` or `merriv` names at decision time. That is collision screening,
not a legal trademark opinion. Public package publishing remains gated by the
repository variable `MERRIV_BRAND_CLEARED=true`, which the owner sets only after
the desired legal/domain/account checks are recorded.
