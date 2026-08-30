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

## Technical identifiers

Before the first Merriv PyPI release, the Python distribution, import namespace,
executable, project-owned plugin and executor identifiers, cache environment
variable, release artifacts, and identity hash domains were unified under
`merriv` or `MERRIV`. The protocol-owned `mcr:` content IDs, JSON field names,
filenames, and schema identifiers remain brand-neutral.

The canonical GitHub repository is `github.com/niansia/Merriv`; public
documentation and package metadata use that locator.

## Distribution

The PyPI project and distribution are `merriv`. The reproducible published-alpha
form pins the version and interpreter:

```console
uvx --python 3.13 --from merriv==0.1.0a3 merriv --help
```

## Clearance boundary

General web and package-index searches found no software project occupying the
exact `Merriv` or `merriv` names at decision time. That is collision screening,
not a legal trademark opinion. Public package publishing remains gated by the
repository variable `MERRIV_BRAND_CLEARED=true`, which the owner set before the
first release and must keep under explicit review for later releases.
