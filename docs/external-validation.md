# External validation guide

Merriv's current phase is problem discovery and contract review. The objective is
to learn whether release-evidence fragmentation is real, urgent, and important
enough that a team would change part of its workflow. This is not a sales script,
an adoption claim, or a request for endorsement.

MCR 0.4 is frozen while this work runs. A field request becomes protocol work
only when a real workflow exposes a blocking semantic problem.

## Validation targets

Prioritize people who directly build or approve deployable model artifacts:

- model optimization and quantization engineers;
- inference/runtime and ML compiler engineers;
- ML platform and model registry owners;
- model release and release engineering teams; and
- teams with traceability requirements across organizational boundaries.

Useful release changes include quantization, compiler or runtime upgrades,
backend migrations, hardware-specific builds, and model promotion in CI.

The first discovery round targets ten conversations. Diversity of workflow is
more useful than ten people from the same team.

## 25-minute problem-discovery conversation

Spend the first 15–20 minutes on the participant's current process. Do not show
MCR until the workflow and pain are understood.

1. Pick one recent baseline → candidate artifact change. Who decided whether it
   could be released, and what could stop the release?
2. Where did the decision evidence live: CI artifacts, evaluation database,
   MLflow, registry metadata, notebook, dashboard, ticket, or chat approval?
3. How did the optimizer/compiler/runtime team hand evidence to the platform or
   deployment team? Was there one shared object or API?
4. Six months later, could someone reconstruct exactly why that candidate was
   allowed or denied? What would be missing or expensive to recover?

Follow up with concrete examples:

- What was the most recent failure or near miss?
- How many people or systems participated in the handoff?
- How often does this release path run?
- What is the consequence of a wrong decision or incomplete record?
- Which evidence cannot be retained or disclosed?
- What workaround exists today, and why has the team kept it?

Only after that, show the Model Change Report boundary and ask:

- Where could this object enter and leave the current workflow?
- Which required field cannot be produced reliably?
- Which field duplicates data that already has a better system of record?
- Which consumer check cannot be implemented independently?
- What is the smallest integration the team would actually try?

## Workflow map

Capture one real release, not an idealized architecture:

```text
baseline source
      ↓
optimization / compilation
      ↓
candidate artifact
      ↓
evaluation and backend checks
      ↓
registry / CI evidence handoff
      ↓
human or automated approval
      ↓
deployment
```

For every transition, record the owner, system of record, artifact identity,
evidence format, decision state, retention period, and manual step. Mark where
evidence is copied into prose, screenshots, dashboards, or chat.

Use this sanitized note template:

```text
Participant role and workflow type:
Release change discussed:
Decision owner:
Systems/evidence locations:
Current handoff object:
Reconstruction after six months:
Recent failure or cost:
MCR fields that map cleanly:
MCR fields unavailable or ambiguous:
Smallest plausible integration:
Problem signal (none / weak / strong):
Urgency signal (none / weak / strong):
Willingness signal (none / weak / strong):
Next evidence or follow-up:
```

Do not publish company names, private artifacts, model outputs, credentials, or
workflow details without explicit permission. An anonymized finding is better
than a falsely precise public claim.

## Interpreting signals

Treat agreement with the idea as weak evidence. Prefer observed behavior and a
specific recent release.

| Dimension | Weak signal | Strong signal |
|---|---|---|
| Problem | General annoyance or hypothetical concern | Evidence is fragmented in a named recent release |
| Urgency | No material consequence or owner | Regression risk, audit cost, debugging delay, or handoff failure |
| Willingness | Would read a document or star the repository | Will map a workflow, provide a fixture, or implement a bounded producer/consumer |

Record objections and rejections. A workflow that does not need MCR is a useful
boundary result, not a failed interview.

## Maintainer design review

Ask reviewers to assume their pipeline does not import Merriv and must produce or
consume MCR 0.4 independently:

> Where does this contract break against one real release workflow? Identify the
> unavailable fields, ambiguous semantics, unacceptable producer burden,
> evidence that cannot be retained, and consumer checks that cannot be
> implemented independently.

Use [issue #18](https://github.com/niansia/Merriv/issues/18) for public findings or
the [release workflow review form](https://github.com/niansia/Merriv/issues/new?template=release-workflow-review.yml)
for a structured, sanitized map.

## Outreach copy

One-to-one request:

> I'm exploring whether model release evidence breaks down between optimization,
> runtime, evaluation, registry, and deployment teams. I'm not asking you to
> adopt a tool. Could we map one real baseline → candidate release for 25 minutes
> and identify where the evidence lived and what could still be reconstructed six
> months later? After that, if relevant, I'd like you to attack a frozen portable
> report contract and show me where it fails.

Public request:

> I'm exploring a portable release-evidence contract for deployable AI artifacts.
> MCR 0.4 is frozen for external review, and I'm specifically looking for real
> production workflows that break it—not endorsements or stars. If you work on
> model optimization, inference runtimes, ML compilers, platform, or release
> engineering, I'd value one sanitized baseline → candidate workflow map or an
> independently implemented producer/consumer critique.

## First-phase success criteria

Repository-owned examples do not count.

- ten structured target-user conversations;
- one serious external maintainer review;
- one real release workflow map;
- one independently maintained MCR producer or consumer; and
- one independent hardware/runtime reproduction.

The first three conversations are a calibration pass. After all ten, summarize
recurring pain, explicit no-problem results, urgency, willingness, unavailable
fields, and smallest integrations. Do not respond to every objection by adding a
field. Change MCR 0.4 only for a demonstrated blocking semantic bug; otherwise
carry validated needs into a later-version backlog.
