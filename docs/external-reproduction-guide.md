# External reproduction guide

Independent reproduction is more valuable than another repository-owned demo.
Use this procedure for a CPU corpus case or target-GPU run.

1. Start from an immutable source commit and record the clean/dirty state.
2. Record artifact, suite, policy, dependency-lock, driver/runtime, and command
   digests before execution. Do not substitute regenerated inputs silently.
3. Run the documented producer without editing predictions or selecting a slice
   after observing failures.
4. Preserve raw tool-native output, native exit code, exact artifact bytes, build
   inputs/parameters, runtime profile, MCR bundles, and bisect boundary.
5. Run strict verification for every MCR and `merriv mcr verify-target` for a target
   archive. Record the target evidence ID and archive SHA-256 externally.
6. Report deviations, missing measurements, and failed commands. An unavailable
   VRAM counter or non-recomputable metric is a limitation, not zero or PASS.
7. Open the external-reproduction issue form with public sanitized evidence. If
   artifacts cannot be public, report only the reproducible metadata and do not
   claim public independent verification.

A reproduction is independent only when the executor controls its environment and
retains its own evidence. Re-uploading the project's archive, running preflight,
or regenerating a normalized fixture does not qualify.
