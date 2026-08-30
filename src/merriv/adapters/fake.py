"""Deterministic offline adapter used by contract tests and plugin authors."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from merriv.adapters.base import AdapterCapability
from merriv.core.identity import fingerprint, observation_content_id
from merriv.core.models import EvalCase, ModelSnapshot, Observation, RuntimeProfile


@dataclass(frozen=True)
class FakeAdapter:
    """Return declared case responses, or echo the case input when none is declared."""

    snapshot: ModelSnapshot
    responses: Mapping[str, Any] = field(default_factory=dict)

    def describe(self) -> ModelSnapshot:
        return self.snapshot

    def capabilities(self) -> frozenset[AdapterCapability]:
        return frozenset({AdapterCapability.BATCH})

    def run(
        self,
        cases: Sequence[EvalCase],
        profile: RuntimeProfile,
    ) -> tuple[Observation, ...]:
        observations: list[Observation] = []
        for case in cases:
            output = self.responses.get(case.case_id, case.input)
            output_digest = fingerprint(output, namespace="observation-output")
            observations.append(
                Observation(
                    id=observation_content_id(
                        snapshot_id=self.snapshot.id,
                        case_id=case.case_id,
                        seed=profile.seed,
                        output_digest=output_digest,
                    ),
                    snapshot_id=self.snapshot.id,
                    case_id=case.case_id,
                    seed=profile.seed,
                    output=output,
                    output_digest=output_digest,
                )
            )
        return tuple(observations)
