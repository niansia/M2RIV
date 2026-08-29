# RFC-0001: Project Scope and Category

- Decision status: Accepted
- Implementation status: Implemented for v0.1
- Target: v0.1

## Decision

M2RIV defines the Model Release Engineering layer between model creation or
registry and production serving. It answers four release questions:

1. What changed?
2. Is the change supported by sufficient evidence?
3. Where did a regression begin?
4. Should the candidate ship?

M2RIV is local-first, provider-agnostic, and CI-native. It is not a training
framework, model registry, benchmark collection, or general observability SaaS.

## Success condition for v0.1

A new user can compare two local models or endpoints in under ten minutes and
receive a portable report containing paired changes, uncertainty, representative
evidence, and explicit limitations.
