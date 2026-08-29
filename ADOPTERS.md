# Adopters and independent implementations

No external production adopter or independently maintained MCR implementation has
been publicly verified yet. Repository-owned Python, Node, Rust, Polygraphy, and
MLflow references are conformance evidence, not external adoption.

Projects may add themselves by pull request when they can link public, retained
evidence for at least one of these claims:

- an MCR producer maintained outside this repository;
- an MCR consumer that preserves PASS/WARN/BLOCK/ERROR without importing M2RIV;
- a CI gate used by an organization on real model-release changes;
- an independently reproduced regression-corpus or target-GPU case.

An entry must name the implementation/revision, MCR version, role, public source
or immutable receipt, verification date, limitations, and maintainer. Dry runs,
normalized fixtures, planned integrations, stars, and package downloads do not
qualify. Withdrawn or stale entries remain visible with their status so adoption
claims cannot silently disappear.
