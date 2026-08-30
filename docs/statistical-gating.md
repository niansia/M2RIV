# Statistical gate semantics

Merriv evaluates every rule in one policy as a declared comparison family. The
default method is Holm-Bonferroni with `familywise_alpha: 0.05`; `none` must be an
explicit policy choice for interval-only gating and does not mean an unadjusted
formal hypothesis test.

For each governed metric, the paired bootstrap retains the percentile intervals
needed by every Holm step. Hypothesis-test evidence is separate: continuous
effects use a paired sign-randomization test centered at the rule margin, while a
binary effect at a zero margin uses the exact two-sided McNemar test. Ordinary
percentile-bootstrap tail counts are not treated as formal p-values.

Matched-binary risk differences at a **non-zero** margin are currently an
unsupported formal-test profile. Centering differences from the binary support
`{-1, 0, +1}` at a non-zero null does not generally produce the sign symmetry
required by the randomization test. Merriv therefore emits no formal p-value for
that combination. A Holm policy that requires it returns `ERROR`; it never
silently substitutes the continuous sign-randomization method. A policy may
explicitly select `multiple_comparison_method: none` for interval-only evaluation,
but that opts out of the formal multiplicity-controlled profile and is not a
matched-binary non-inferiority test.

Future support must select and validate a method designed for paired binary
non-inferiority, such as a score-based or unconditional exact procedure, rather
than reusing the continuous test. Relevant primary references include
[Tango's paired-proportion method](https://pubmed.ncbi.nlm.nih.gov/9595618/) and
[Hsueh, Liu, and Chen's unconditional exact procedure](https://doi.org/10.1111/j.0006-341X.2001.00478.x).

Merriv deliberately uses a **two-sided** test and two-sided interval even though
non-inferiority is commonly framed as a one-sided question. A release gate must
classify conclusive violations as well as conclusive passes, and an unexpectedly
large improvement can itself indicate pairing, leakage, or instrumentation error.
This costs power relative to a one-sided design; the choice is conservative and
explicit rather than accidental.

The sign-randomization test assumes independent cases and exchangeable signs for
paired differences centered at the null. It is enumerated exactly for at most 16
pairs and otherwise uses a deterministic Monte Carlo estimate with the plus-one
correction. Holm orders these raw p-values, breaks exact ties by `rule_id`,
computes monotone adjusted p-values, and selects the confidence level for each
step. A Holm rule is decisive only when its adjusted test is significant **and**
the full selected interval lies on one side of the margin. Point estimates never
PASS or BLOCK by themselves.

The percentile-bootstrap confidence interval is an independent interval-evidence
requirement; it is **not** the inversion of the reported sign-randomization or
McNemar test. The two requirements are intentionally combined conservatively.
A future statistical profile may pair each test with a method-compatible
confidence set, but MCR 0.4 and GatePolicy 1.1 do not claim that duality.

## Declared family

`family_size` is the number of rules declared in the policy—not the number that
happened to produce a testable p-value in one run. Missing evidence, `ERROR`, and
`INSUFFICIENT_POWER` rules remain in the denominator. This is intentionally
conservative: declaring rules that are predictably unevaluable cannot dilute the
correction applied to the rules that were tested. It can make the remaining rules
less decisive, while the incomplete rules already keep the overall decision
fail-closed.

```yaml
schema_version: 1.1.0
policy_id: regulated-release-v1
multiple_comparison_method: holm-bonferroni
familywise_alpha: 0.05
target_power: 0.8
rules:
  - rule_id: critical-slice-quality
    metric: mean_quality_score@risk=critical
    direction: higher_is_better
    margin: 0.02
    max_mde: 0.02
    planned_difference_stddev: 0.04
```

`max_mde` is the largest minimum detectable effect the policy accepts. The
decision-bearing MDE uses the prospectively specified paired-difference standard
deviation and the normal-approximation design formula

`(z_(1-alpha/2) + z_power) * s_difference / sqrt(n)`.

For Holm policies, the power check uses the conservative first-step alpha
`familywise_alpha / family_size`. A rule with `max_mde` must also declare
`planned_difference_stddev`; if the resulting planned-design MDE exceeds
`max_mde`, the rule returns `INSUFFICIENT_POWER`. That state is always fail-closed
and cannot satisfy the evaluation policy through `allow_warn`.

When no planned standard deviation is declared, Merriv still reports an
observed-design MDE as a diagnostic sensitivity summary. It never uses that
post-hoc quantity to satisfy or fail a `max_mde` gate. Very small,
unrepresentative, or zero-variance slices still require domain judgment. A policy
may retain `min_pairs` for a cohort floor, but it has no default and is not a
substitute for a prospective MDE requirement.

`planned_difference_stddev` was added in GatePolicy 1.1.0. This is an additive
tooling-policy revision; it does not add a field to the frozen Model Change
Report 0.4 envelope or alter its content-identity preimage.
