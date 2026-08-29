# RFC 0005: Network adapters and regression-bisect threat model

- Decision status: Accepted
- Implementation status: Implemented for v0.1
- Audience: adapter, release-gate, and CI maintainers

## Context

Stage 4 adds two trust-boundary crossings: remote inference endpoints and automated
search for the first bad model revision. Both features can turn a bounded local
comparison into an unbounded network or compute job. They also process attacker-
controlled URLs, headers, response bodies, revision labels, callbacks, and error
messages.

M2RIV's release decision is security-sensitive. A failure to evaluate is not
evidence that a candidate is safe. Network and callback failures therefore fail
closed as `ERROR`; they must never be collapsed into `PASS`, `WARN`, a neutral
metric, or a guessed regression onset.

## Assets and invariants

The implementation protects:

1. API keys, bearer tokens, URL userinfo, prompts, and provider response bodies.
2. The integrity and bounded cost of a comparison run.
3. Snapshot, cache, report, and error-channel confidentiality.
4. The claim that a reported onset is supported by observed, monotonic evidence.

The following invariants are normative:

- Secrets are accepted through runtime-only fields and are excluded from model
  snapshots, fingerprints, cache keys and values, reports, logs, exception text,
  `repr`, and CLI output.
- Credential-dependent routing is represented by a caller-declared, non-secret
  credential scope. A credential or credential hash is never persisted as identity.
- Mutable remote deployments do not reuse observations across invocations by
  default. Persistent reuse requires an immutable deployment revision in identity.
- Endpoint identity may include a normalized origin/path and non-secret behavior
  configuration, but never URL userinfo, query credentials, or authorization
  headers.
- Only explicit `http` and `https` endpoint schemes are accepted. Userinfo and
  fragments are rejected. Redirect policy is bounded and must not forward
  credentials across origins.
- Response bytes, JSON nesting, output tokens, request count, wall-clock time,
  concurrency, attempts, and cumulative retry delay have explicit limits.
- Retry applies only to configured transient outcomes. `Retry-After` is parsed
  defensively, capped by the remaining retry and wall-clock budgets, and cannot
  increase the total attempt budget.
- A network error, malformed response, missing case, duplicate case, callback
  exception, or budget exhaustion becomes typed `ERROR` evidence.
- Bisect never labels `WARN` or `ERROR` as good. It does not invent an onset when
  evidence is non-monotonic, incomplete, or callback execution failed.

## Threats and controls

### Credential disclosure

Attackers may induce an endpoint exception containing request headers, embed a key
in a URL, return it in a response, or rely on dataclass/Pydantic serialization.
Adapters keep authentication in an opaque, private runtime carrier, construct
sanitized errors, and test the serialized snapshot/cache/report/error surfaces for
known canary secrets. Authorization values must be redacted before diagnostic
hooks receive metadata.

Two credentials can route the same public endpoint/model name to different tenants
or deployments. Baseline and candidate cache namespaces are always distinct, and
the endpoint adapter accepts a non-secret credential scope plus deployment revision
for snapshot identity. The CLI uses an ephemeral cache for remote comparisons so a
provider-mutated model cannot inherit stale evidence from an earlier run.

### SSRF and URL confusion

Non-HTTP schemes (`file`, `data`, `ftp`, custom transports), URL userinfo, protocol-
relative endpoints, and credentials in query strings are rejected. Known metadata
hostnames, link-local IPv4/IPv6 (including legacy numeric and IPv4-mapped forms),
AWS's unique-local metadata address, and catalogued non-link-local metadata
addresses such as `100.100.100.200` are also rejected. Loopback, RFC 1918, and
overlay-network endpoints remain supported for self-hosted inference, so this is
not a general private-address ban. Operators remain responsible for network egress
policy and DNS-rebinding defenses; deployments evaluating untrusted endpoint URLs
should use an egress-restricted worker.

### Retry and response amplification

`429`, `502`, `503`, and `504` can amplify spend if retries are unbounded. Attempts
and total elapsed time are fixed before the first request. Backoff and
`Retry-After` are capped, randomized only from a deterministic/testable source when
required, and cancelled when the remaining budget is insufficient. Large or
streaming responses are stopped after the configured byte/token ceiling.

### Input parser denial of service

Suite JSONL and policy YAML are locally supplied but may originate in a pull
request. Loaders enforce whole-file, per-line, row-count, alias-count, and nesting
limits before materializing unbounded objects. JSON constants `NaN`, `Infinity`,
and `-Infinity` are rejected. Duplicate mapping keys and duplicate case IDs are
errors. YAML safe construction alone is not a resource bound.

### CI output injection

JUnit is emitted through XML escaping and SARIF through JSON encoding. Rule IDs and
messages remain data, never XML elements, Markdown/HTML, terminal control commands,
or filesystem paths. GitHub summaries contain only the already-sanitized MCR and
are written only to the runner-provided summary path; secrets and raw model output
are excluded. Symlink/reparse-point behavior is treated as a runner trust concern
and should be rejected where the platform provides a reliable primitive.

### Local cache amplification and path redirection

A cache may outlive the process that created it or be mounted into several workers.
Cache reads treat oversized, non-regular, malformed, identity-mismatched, symlink,
and reparse-point entries as misses. Reads use a bounded file descriptor rather
than materializing an arbitrary path in one operation. Writes reject envelopes
over the same byte ceiling and refuse symlink/reparse-point roots, shards, and
targets before atomic replacement. A cache shared with a concurrently malicious
local writer still requires operating-system isolation: portable path checks cannot
eliminate every ancestor-swap race on every supported platform.

### False bisect onset

Binary search assumes a monotonic predicate. Model quality is frequently noisy or
non-monotonic. The bisector verifies endpoints and the proposed boundary, records
every evaluated revision, and detects contradictory `good` after `bad` evidence.
`WARN` means inconclusive, not good. `ERROR` means the run is invalid, not bad. A
callback exception is converted into a typed error with a sanitized message. The
result has no onset unless all required evidence is decisive and consistent.

## Decision-state table

| Observation | Release meaning | Bisect classification |
|---|---|---|
| `PASS` | evaluated and allowed | good |
| `BLOCK` | evaluated and disallowed | bad |
| `WARN` | insufficient or uncertain | inconclusive; no onset |
| `ERROR` | evaluation invalid | error; no onset |

## Required adversarial verification

Before release, tests cover YAML aliases/oversize/depth, JSONL non-finite numbers,
huge lines/row counts/duplicates, XML and SARIF metacharacters, secret canaries on
all persistence and error surfaces, forbidden URL forms, capped `Retry-After`,
non-monotonic bisect evidence, `WARN`/`ERROR` handling, and callback exceptions.

## Non-goals

This RFC does not promise a general sandbox for arbitrary adapters, guarantee that
remote providers do not retain requests, or replace cluster-level egress, secret
management, rate limiting, and billing controls.
