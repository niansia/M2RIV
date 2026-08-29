# MCR design-partner playbook

The next adoption milestone is three retained external CI uses, not more core
features. Target one team in each cohort: LLM inference, CV/edge, and
compiler/runtime.

## Ten-minute first contact

1. Show the 15-second ONNX rare-slice regression and first-bad build.
2. Show one MCR JSON plus `m2riv mcr verify --strict`.
3. Ask for one real artifact change they already fear shipping.
4. Integrate their existing oracle; do not replace it.
5. Retain one baseline, one known-bad candidate, policy, MCR, and CI receipt.

## Discovery questions

- What exact artifact or runtime change triggers release review?
- Which existing tool produces the trusted raw result?
- What promotion system consumes the verdict?
- Which slice, hardware cohort, or cost boundary has failed before?
- What evidence must survive an incident review six months later?
- Who is allowed to override WARN/BLOCK, and where is that recorded?

## Pilot acceptance criteria

- exact baseline/candidate identities and tool versions;
- at least one policy that can produce BLOCK;
- retained raw evidence and strict MCR verification;
- no credentials or mutable remote identities in evidence;
- one CI run executed by the partner;
- written feedback on missing or confusing MCR semantics.

Public case studies, names, logos, telemetry, and repository access require
separate permission. A repository-owned demo is not counted as a design partner.

## Outreach artifact

Send the demo command, the two-platform numerical-diff table, a five-line MCR
summary, and one precise question about their release chain. Do not lead with the
historical PDF or a claim that existing tools cannot gate releases.
