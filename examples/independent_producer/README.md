# Independent MCR producer

`generate_bundle.py` is a deliberately small, standard-library-only producer. It
does not import Merriv. It implements RFC 0012 content identity directly and emits
the complete fixture in `examples/mcr_conformance/full/`.

```console
python examples/independent_producer/generate_bundle.py --check
merriv mcr verify examples/mcr_conformance/full
```

The full fixture exercises stable evidence and run IDs, a release plan, evidence
manifest and set, artifact diff, numerical diff, and direct finding/metric set
references. It is conformance evidence, not an inference result.
