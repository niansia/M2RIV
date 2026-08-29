# MCR 1.3 conformance fixtures

These minimal `PASS`, `WARN`, and `BLOCK` reports exercise the portable MCR
consumer boundary without depending on a model, suite, or M2RIV-internal runner.
Their executor identifies itself as `example.external-producer`, demonstrating
that the report contract is not restricted to bundles emitted by the M2RIV CLI.

Verify one fixture:

```console
m2riv mcr verify examples/mcr_conformance/block
```

All three valid decision states return verifier exit code 0 because integrity
verification is separate from release authorization. The JSON result still
surfaces `decision_status`; CI gates should act on the original producer decision
or use the reusable M2RIV action to compare and enforce it directly.

Regenerate or check the committed fixtures after a contract change:

```console
python examples/mcr_conformance/generate_fixtures.py
python examples/mcr_conformance/generate_fixtures.py --check
```
