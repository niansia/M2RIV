# MCR conformance self-certification

MCR is not currently governed by a standards organization, and the project does
not authorize third parties to imply endorsement. “MCR conformant” means only
that a named implementation version produced a retained successful result from
the public conformance suite.

A reproducible self-certification record must include:

- implementation name, version, source revision, and license;
- MCR envelope version and conformance-suite revision;
- producer and/or consumer profile result JSON;
- operating system, architecture, language/runtime, and command line;
- CI run or immutable evidence URI with checksum;
- known skipped capabilities and limitations;
- date and responsible maintainer.

Results expire when the implementation, MCR minor/major version, canonical
identity rules, or relevant decision semantics change. A failing or skipped
profile cannot be represented as passing. Merriv names and marks remain governed
by the project brand policy; passing the suite grants no trademark license.

The future path to neutral certification is: two independent implementations,
published governance, versioned test vectors, an appeals/correction process, and
a public result registry that records both passes and withdrawals.
