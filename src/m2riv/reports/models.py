"""Machine-portable Model Change Report (MCR) candidate envelope."""

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
    PASS = "PASS"  # nosec B105  # noqa: S105 - release status, not a credential
    WARN = "WARN"
    INSUFFICIENT_POWER = "INSUFFICIENT_POWER"
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
    media_type: Literal["application/vnd.model-change-report.evidence-manifest+json"] = (
        "application/vnd.model-change-report.evidence-manifest+json"
    )
    evidence_count: int = Field(ge=1)
    set_count: int = Field(ge=1)


def create_evidence_set(evidence: tuple[EvidenceRef, ...]) -> EvidenceSet:
    """Create a reusable content-addressed membership list."""
    if not evidence:
        raise ValueError("evidence set must contain at least one reference")
    members = tuple(item.id for item in evidence)
    identifier = fingerprint({"members": members}, namespace="evidence-set")
    return EvidenceSet(id=f"mcr:sha256:{identifier}", count=len(members), members=members)


def create_evidence_manifest(
    evidence: tuple[EvidenceRef, ...], sets: tuple[EvidenceSet, ...]
) -> EvidenceManifest:
    """Create a manifest whose identity covers entries and set membership."""
    payload = {"schema_version": "1.0.0", "evidence": evidence, "sets": sets}
    identifier = fingerprint(payload, namespace="evidence-manifest")
    return EvidenceManifest(id=f"mcr:sha256:{identifier}", evidence=evidence, sets=sets)


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
    confidence_level: FiniteFloat | None = Field(default=None, gt=0, lt=1)
    interval_lower: FiniteFloat | None = None
    interval_upper: FiniteFloat | None = None
    raw_p_value: FiniteFloat | None = Field(default=None, ge=0, le=1)
    adjusted_p_value: FiniteFloat | None = Field(default=None, ge=0, le=1)
    effective_alpha: FiniteFloat | None = Field(default=None, gt=0, lt=1)
    minimum_detectable_effect: FiniteFloat | None = Field(default=None, ge=0)
    target_power: FiniteFloat | None = Field(default=None, gt=0.5, lt=1)

    @model_validator(mode="after")
    def statistical_interval_is_complete(self) -> MCRFinding:
        interval = (self.confidence_level, self.interval_lower, self.interval_upper)
        if any(value is None for value in interval) and not all(
            value is None for value in interval
        ):
            raise ValueError("finding confidence level and interval bounds must be complete")
        if (
            self.interval_lower is not None
            and self.interval_upper is not None
            and self.interval_lower > self.interval_upper
        ):
            raise ValueError("finding interval_lower must not exceed interval_upper")
        return self


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
    """Portable verdict for the evaluation policy bound into this MCR.

    ``allowed`` is the frozen MCR 0.4 wire name. It means the candidate satisfies
    this report's evaluation policy; it never grants deployment or promotion
    authority to the evidence producer.
    """

    status: MCRStatus
    allowed: bool
    findings: tuple[MCRFinding, ...] = ()
    multiple_comparison_method: Literal["none", "holm-bonferroni"] = "none"
    familywise_alpha: FiniteFloat | None = Field(default=None, gt=0, lt=1)
    family_size: int | None = Field(default=None, ge=1)
    target_power: FiniteFloat | None = Field(default=None, gt=0.5, lt=1)

    @property
    def evaluation_policy_satisfied(self) -> bool:
        """Return the unambiguous local name for the MCR 0.4 ``allowed`` field."""

        return self.allowed

    @model_validator(mode="after")
    def status_matches_allowed(self) -> MCRDecision:
        if self.status is MCRStatus.PASS and not self.allowed:
            raise ValueError("allowed must be True when status is PASS")
        if self.status in {
            MCRStatus.INSUFFICIENT_POWER,
            MCRStatus.BLOCK,
            MCRStatus.ERROR,
        } and self.allowed:
            raise ValueError(f"allowed must be False when status is {self.status.value}")
        family = (self.familywise_alpha, self.family_size, self.target_power)
        if any(value is None for value in family) and not all(value is None for value in family):
            raise ValueError("family-wise alpha, family size, and target power are one contract")
        if self.multiple_comparison_method == "holm-bonferroni" and any(
            value is None for value in family
        ):
            raise ValueError("Holm-Bonferroni decisions require complete family metadata")
        return self


class ModelChangeReport(Contract):
    """The stable envelope Merriv intends other tools to produce and consume."""

    schema_version: Literal["0.4.0"] = "0.4.0"
    id: ContentId
    evidence_id: ContentId
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
    """Create deterministic evidence/report IDs and a volatile run identity.

    ``evidence_id`` covers replay-stable evidence and permits deduplication.
    ``id`` also covers the release decision, so opposite verdicts can never share
    a report identity. ``run_id`` covers the exact serialized run, including its
    timestamp, timing metrics, cache provenance, and limitations.
    """
    timestamp = created_at or datetime.now(UTC)
    finding_payloads: tuple[dict[str, object], ...] = tuple(
        {
            "rule_id": finding.rule_id,
            "status": finding.status,
            "message": finding.message,
            "metric_id": finding.metric_id,
            "evidence": finding.evidence,
            "evidence_set_id": finding.evidence_set_id,
            **(
                {"confidence_level": finding.confidence_level}
                if finding.confidence_level is not None
                else {}
            ),
            **(
                {"interval_lower": finding.interval_lower}
                if finding.interval_lower is not None
                else {}
            ),
            **(
                {"interval_upper": finding.interval_upper}
                if finding.interval_upper is not None
                else {}
            ),
            **(
                {"raw_p_value": finding.raw_p_value}
                if finding.raw_p_value is not None
                else {}
            ),
            **(
                {"adjusted_p_value": finding.adjusted_p_value}
                if finding.adjusted_p_value is not None
                else {}
            ),
            **(
                {"effective_alpha": finding.effective_alpha}
                if finding.effective_alpha is not None
                else {}
            ),
            **(
                {"minimum_detectable_effect": finding.minimum_detectable_effect}
                if finding.minimum_detectable_effect is not None
                else {}
            ),
            **(
                {"target_power": finding.target_power}
                if finding.target_power is not None
                else {}
            ),
        }
        for finding in decision.findings
    )
    decision_payload: dict[str, object] = {
        "status": decision.status,
        "allowed": decision.allowed,
        "findings": finding_payloads,
    }
    if decision.multiple_comparison_method != "none":
        decision_payload["multiple_comparison_method"] = decision.multiple_comparison_method
    if decision.familywise_alpha is not None:
        decision_payload["familywise_alpha"] = decision.familywise_alpha
    if decision.family_size is not None:
        decision_payload["family_size"] = decision.family_size
    if decision.target_power is not None:
        decision_payload["target_power"] = decision.target_power
    stable_metric_ids = {
        metric.metric_id for metric in metrics if metric.identity_scope == "evidence"
    }
    evidence_payload = {
        "schema_version": "0.4.0",
        "baseline_snapshot_id": baseline_snapshot_id,
        "candidate_snapshot_id": candidate_snapshot_id,
        "release_plan_id": release_plan_id,
        "metrics": tuple(metric for metric in metrics if metric.identity_scope == "evidence"),
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
    evidence_id = fingerprint(evidence_payload, namespace="model-change-evidence")
    report_payload = {
        "schema_version": "0.4.0",
        "evidence_id": f"mcr:sha256:{evidence_id}",
        "release_plan_id": release_plan_id,
        "decision": decision_payload,
    }
    report_id = fingerprint(report_payload, namespace="model-change-report")
    run_payload = {
        "schema_version": "0.4.0",
        "report_id": f"mcr:sha256:{report_id}",
        "evidence_id": f"mcr:sha256:{evidence_id}",
        "created_at": timestamp,
        "baseline_snapshot_id": baseline_snapshot_id,
        "candidate_snapshot_id": candidate_snapshot_id,
        "release_plan_id": release_plan_id,
        "executions": executions,
        "metrics": metrics,
        "decision": decision_payload,
        "evidence_manifest": evidence_manifest,
        "evidence": evidence,
        "limitations": limitations,
    }
    run_id = fingerprint(run_payload, namespace="model-change-run")
    return ModelChangeReport(
        id=f"mcr:sha256:{report_id}",
        evidence_id=f"mcr:sha256:{evidence_id}",
        run_id=f"mcr:sha256:{run_id}",
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
