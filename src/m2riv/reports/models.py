"""Machine-portable Model Change Report (MCR) v1 envelope."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, FiniteFloat, StringConstraints, model_validator

from m2riv.core.identity import fingerprint
from m2riv.core.models import ContentId, Contract, Digest, EvidenceRef, RuntimeProfile

SafeExecutionCapability = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"),
]


class MCRStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    BLOCK = "BLOCK"
    ERROR = "ERROR"


class EvidenceSet(Contract):
    """Ordered membership in a reusable set of content-addressed evidence."""

    id: ContentId
    count: int = Field(ge=1)
    members: tuple[ContentId, ...] = Field(min_length=1, max_length=1_000_000)

    @model_validator(mode="after")
    def count_matches_members(self) -> EvidenceSet:
        if self.count != len(self.members):
            raise ValueError("evidence set count must match member count")
        return self


class EvidenceManifest(Contract):
    """Externalizable evidence index shared by every metric in one MCR."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    id: ContentId
    evidence: tuple[EvidenceRef, ...] = Field(max_length=1_000_000)
    sets: tuple[EvidenceSet, ...] = Field(min_length=1, max_length=4096)

    @model_validator(mode="after")
    def members_resolve_and_identities_are_unique(self) -> EvidenceManifest:
        evidence_ids = [item.id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence manifest entries must have unique ids")
        set_ids = [item.id for item in self.sets]
        if len(set_ids) != len(set(set_ids)):
            raise ValueError("evidence manifest sets must have unique ids")
        available = set(evidence_ids)
        if any(member not in available for item in self.sets for member in item.members):
            raise ValueError("evidence set member is missing from the manifest")
        return self


class EvidenceManifestRef(Contract):
    """Bounded MCR pointer to an external evidence manifest."""

    id: ContentId
    uri: str = Field(default="evidence-manifest.json", min_length=1, max_length=2048)
    media_type: Literal["application/vnd.m2riv.evidence-manifest+json"] = (
        "application/vnd.m2riv.evidence-manifest+json"
    )
    evidence_count: int = Field(ge=1)
    set_count: int = Field(ge=1)


def create_evidence_set(evidence: tuple[EvidenceRef, ...]) -> EvidenceSet:
    """Create a reusable content-addressed membership list."""
    if not evidence:
        raise ValueError("evidence set must contain at least one reference")
    members = tuple(item.id for item in evidence)
    identifier = fingerprint({"members": members}, namespace="evidence-set")
    return EvidenceSet(id=f"m2riv:sha256:{identifier}", count=len(members), members=members)


def create_evidence_manifest(
    evidence: tuple[EvidenceRef, ...], sets: tuple[EvidenceSet, ...]
) -> EvidenceManifest:
    """Create a manifest whose identity covers entries and set membership."""
    payload = {"schema_version": "1.0.0", "evidence": evidence, "sets": sets}
    identifier = fingerprint(payload, namespace="evidence-manifest")
    return EvidenceManifest(id=f"m2riv:sha256:{identifier}", evidence=evidence, sets=sets)


class MCRMetric(Contract):
    """A paired metric change with uncertainty and evidence pointers."""

    metric_id: str = Field(min_length=1)
    scope: str = "overall"
    unit: str = Field(default="score", min_length=1)
    direction: Literal["higher_is_better", "lower_is_better", "target"] = "higher_is_better"
    baseline_value: FiniteFloat
    candidate_value: FiniteFloat
    delta: FiniteFloat
    confidence_level: FiniteFloat | None = Field(default=None, gt=0, lt=1)
    interval_lower: FiniteFloat | None = None
    interval_upper: FiniteFloat | None = None
    effect_size: FiniteFloat | None = None
    sample_size: int = Field(ge=0)
    evidence_set_id: ContentId | None = None
    identity_scope: Literal["evidence", "run"] = "evidence"

    @model_validator(mode="after")
    def validate_interval(self) -> MCRMetric:
        interval = (self.interval_lower, self.interval_upper, self.confidence_level)
        incomplete = any(value is None for value in interval) and not all(
            value is None for value in interval
        )
        if incomplete:
            raise ValueError("confidence level and both interval bounds must be provided together")
        if (
            self.interval_lower is not None
            and self.interval_upper is not None
            and self.interval_lower > self.interval_upper
        ):
            raise ValueError("interval_lower must not exceed interval_upper")
        return self


class MCRFinding(Contract):
    rule_id: str = Field(min_length=1)
    status: MCRStatus
    message: str = Field(min_length=1)
    metric_id: str | None = None
    evidence: tuple[EvidenceRef, ...] = Field(default=(), max_length=128)
    evidence_set_id: ContentId | None = None


class MCRExecution(Contract):
    """Execution-fabric provenance for one side of a paired comparison."""

    role: Literal["baseline", "candidate"]
    executor_id: str = Field(min_length=1)
    executor_version: str = Field(min_length=1)
    config_fingerprint: Digest
    runtime_profile: RuntimeProfile | None = None
    capabilities: frozenset[SafeExecutionCapability] = Field(
        default_factory=frozenset, max_length=64
    )
    requested_cases: int = Field(ge=0)
    returned_observations: int = Field(ge=0)
    cache_hits: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def returned_cannot_exceed_requested(self) -> MCRExecution:
        if self.returned_observations > self.requested_cases:
            raise ValueError("returned observations cannot exceed requested cases")
        return self


class MCRDecision(Contract):
    """Portable gate verdict with an explicit release disposition."""

    status: MCRStatus
    allowed: bool
    findings: tuple[MCRFinding, ...] = ()

    @model_validator(mode="after")
    def status_matches_allowed(self) -> MCRDecision:
        if self.status is MCRStatus.PASS and not self.allowed:
            raise ValueError("allowed must be True when status is PASS")
        if self.status in {MCRStatus.BLOCK, MCRStatus.ERROR} and self.allowed:
            raise ValueError(f"allowed must be False when status is {self.status.value}")
        return self


class ModelChangeReport(Contract):
    """The stable envelope M2RIV intends other tools to produce and consume."""

    schema_version: Literal["1.3.0"] = "1.3.0"
    id: ContentId
    run_id: ContentId
    created_at: datetime
    baseline_snapshot_id: ContentId
    candidate_snapshot_id: ContentId
    release_plan_id: ContentId | None = None
    executions: tuple[MCRExecution, ...] = ()
    metrics: tuple[MCRMetric, ...] = ()
    decision: MCRDecision
    evidence_manifest: EvidenceManifestRef | None = None
    evidence: tuple[EvidenceRef, ...] = Field(default=(), max_length=128)
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_created_at(self) -> ModelChangeReport:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        roles = [execution.role for execution in self.executions]
        if len(roles) != len(set(roles)):
            raise ValueError("execution roles must be unique")
        if (
            any(metric.evidence_set_id is not None for metric in self.metrics)
            or any(finding.evidence_set_id is not None for finding in self.decision.findings)
        ) and self.evidence_manifest is None:
            raise ValueError(
                "metric or finding evidence sets require an evidence manifest reference"
            )
        return self


def create_report(
    *,
    baseline_snapshot_id: str,
    candidate_snapshot_id: str,
    release_plan_id: str | None = None,
    executions: tuple[MCRExecution, ...] = (),
    metrics: tuple[MCRMetric, ...],
    decision: MCRDecision,
    evidence_manifest: EvidenceManifestRef | None = None,
    evidence: tuple[EvidenceRef, ...] = (),
    limitations: tuple[str, ...] = (),
    created_at: datetime | None = None,
) -> ModelChangeReport:
    """Create separate deterministic evidence and volatile run identities.

    ``id`` covers replay-stable release evidence. ``run_id`` covers the exact
    serialized run, including its timestamp, timing metrics, cache provenance,
    and verdict. This lets identical model outputs deduplicate while preserving
    an address for every measured execution.
    """
    timestamp = created_at or datetime.now(UTC)
    stable_metric_ids = {
        metric.metric_id for metric in metrics if metric.identity_scope == "evidence"
    }
    evidence_payload = {
        "schema_version": "1.3.0",
        "baseline_snapshot_id": baseline_snapshot_id,
        "candidate_snapshot_id": candidate_snapshot_id,
        "release_plan_id": release_plan_id,
        "metrics": tuple(
            metric for metric in metrics if metric.identity_scope == "evidence"
        ),
        "finding_evidence": tuple(
            {
                "rule_id": finding.rule_id,
                "metric_id": finding.metric_id,
                "evidence_set_id": finding.evidence_set_id,
                "evidence": finding.evidence,
            }
            for finding in decision.findings
            if finding.metric_id is None or finding.metric_id in stable_metric_ids
        ),
        "evidence_manifest": evidence_manifest,
        "evidence": evidence,
    }
    report_id = fingerprint(evidence_payload, namespace="model-change-evidence")
    run_payload = {
        "schema_version": "1.3.0",
        "evidence_id": f"m2riv:sha256:{report_id}",
        "created_at": timestamp,
        "baseline_snapshot_id": baseline_snapshot_id,
        "candidate_snapshot_id": candidate_snapshot_id,
        "release_plan_id": release_plan_id,
        "executions": executions,
        "metrics": metrics,
        "decision": decision,
        "evidence_manifest": evidence_manifest,
        "evidence": evidence,
        "limitations": limitations,
    }
    run_id = fingerprint(run_payload, namespace="model-change-run")
    return ModelChangeReport(
        id=f"m2riv:sha256:{report_id}",
        run_id=f"m2riv:sha256:{run_id}",
        created_at=timestamp,
        baseline_snapshot_id=baseline_snapshot_id,
        candidate_snapshot_id=candidate_snapshot_id,
        release_plan_id=release_plan_id,
        executions=executions,
        metrics=metrics,
        decision=decision,
        evidence_manifest=evidence_manifest,
        evidence=evidence,
        limitations=limitations,
    )
