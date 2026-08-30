# Statistical gate semantics

Merriv evaluates every rule in one policy as a declared comparison family. The
default method is Holm-Bonferroni with `familywise_alpha: 0.05`; `none` must be an
explicit policy choice when no multiplicity correction is wanted.

For each governed metric, the paired bootstrap retains the percentile intervals
needed by every Holm step and tail evidence at that rule's non-inferiority margin.
Holm orders the raw two-sided tail probabilities, computes adjusted p-values, and
selects the confidence level for each step. A rule is decisive only when the full
selected interval lies on one side of the margin. Point estimates never PASS or
BLOCK by themselves.

```yaml
schema_version: 1.0.0
policy_id: regulated-release-v1
multiple_comparison_method: holm-bonferroni
familywise_alpha: 0.05
target_power: 0.8
rules:
  - rule_id: critical-slice-quality
    metric: accuracy@risk=critical
    direction: higher_is_better
    margin: 0.02
    max_mde: 0.02
```

`max_mde` is the largest minimum detectable effect the policy accepts. The
reported MDE uses the observed paired-difference standard deviation and the
normal-approximation design formula

`(z_(1-alpha/2) + z_power) * s_difference / sqrt(n)`.

For Holm policies, the power check uses the conservative first-step alpha
`familywise_alpha / family_size`. If the observed-design MDE exceeds `max_mde`,
the rule returns `INSUFFICIENT_POWER`. That state is always fail-closed and cannot
satisfy the evaluation policy through `allow_warn`.

This is a sensitivity summary, not prospective sample-size magic. It depends on
the observed paired spread; very small, unrepresentative, or zero-variance slices
still require domain judgment. A policy may retain `min_pairs` for a cohort floor,
but it has no default and is not a substitute for a declared MDE requirement.
