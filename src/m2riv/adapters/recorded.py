"""Offline adapter for previously captured model outputs in JSONL form."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, ValidationError

from m2riv.adapters.base import AdapterCapability
from m2riv.core.identity import fingerprint
from m2riv.core.models import EvalCase, ModelSnapshot, Observation, RuntimeProfile
from m2riv.io.loaders import InputFormatError, _load_jsonl


class RecordedOutput(BaseModel):
    """One captured output; unknown fields are rejected to prevent silent typos."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    case_id: str = Field(min_length=1)
    output: Any
    latency_ms: FiniteFloat | None = Field(default=None, ge=0)
    traces: dict[str, Any] = Field(default_factory=dict)


class RecordedAdapter:
    """Replay immutable observations without loading or executing a model."""

    def __init__(self, snapshot: ModelSnapshot, records: dict[str, RecordedOutput]) -> None:
        self._snapshot = snapshot
        self._records = records

    @classmethod
    def from_jsonl(cls, path: str | Path, snapshot: ModelSnapshot) -> RecordedAdapter:
        source = Path(path)
        records: dict[str, RecordedOutput] = {}
        for line_number, row in _load_jsonl(source):
            try:
                record = RecordedOutput.model_validate(row)
            except ValidationError as error:
                raise InputFormatError(f"{source}:{line_number}: {error}") from error
            if record.case_id in records:
                raise InputFormatError(
                    f"{source}:{line_number}: duplicate case_id {record.case_id!r}"
                )
            records[record.case_id] = record
        return cls(snapshot=snapshot, records=records)

    def describe(self) -> ModelSnapshot:
        return self._snapshot

    def capabilities(self) -> frozenset[AdapterCapability]:
        return frozenset({AdapterCapability.BATCH})

    def run(
        self,
        cases: Sequence[EvalCase],
        profile: RuntimeProfile,
    ) -> tuple[Observation, ...]:
        observations: list[Observation] = []
        for case in cases:
            record = self._records.get(case.case_id)
            if record is None:
                continue
            output_digest = fingerprint(record.output, namespace="observation-output")
            payload = {
                "snapshot_id": self._snapshot.id,
                "case_id": case.case_id,
                "seed": profile.seed,
                "output_digest": output_digest,
                "latency_ms": record.latency_ms,
                "traces": record.traces,
            }
            observation_id = fingerprint(payload, namespace="observation")
            observations.append(
                Observation(
                    id=f"m2riv:sha256:{observation_id}",
                    snapshot_id=self._snapshot.id,
                    case_id=case.case_id,
                    seed=profile.seed,
                    output=record.output,
                    output_digest=output_digest,
                    latency_ms=record.latency_ms,
                    traces=record.traces,
                )
            )
        return tuple(observations)
