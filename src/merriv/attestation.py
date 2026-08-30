"""in-toto Statement binding for Model Change Report predicates."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from merriv.core.models import Contract
from merriv.reports import ModelChangeReport

Sha256Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
MCR_PREDICATE_TYPE = (
    "https://github.com/niansia/Merriv/attestations/model-change-report/v0.1"
)


class InTotoSubject(Contract):
    """Artifact subject covered by an in-toto Statement."""

    name: str = Field(min_length=1, max_length=2048)
    digest: dict[Literal["sha256"], Sha256Digest]


class MCRAttestationPredicate(Contract):
    """Self-contained MCR predicate; signing belongs to the attestation layer."""

    predicate_version: Literal["0.1.0"] = "0.1.0"
    report: ModelChangeReport


class MCRInTotoStatement(Contract):
    """Unsigned in-toto Statement ready for cosign or another attestor."""

    statement_type: Literal["https://in-toto.io/Statement/v1"] = Field(alias="_type")
    subject: tuple[InTotoSubject, ...] = Field(min_length=1, max_length=128)
    predicate_type: Literal[
        "https://github.com/niansia/Merriv/attestations/model-change-report/v0.1"
    ] = Field(alias="predicateType")
    predicate: MCRAttestationPredicate

    @model_validator(mode="after")
    def report_candidate_is_bound(self) -> MCRInTotoStatement:
        if not self.predicate.report.candidate_snapshot_id:
            raise ValueError("predicate report must identify a candidate snapshot")
        return self


def create_mcr_statement(
    report: ModelChangeReport,
    *,
    subject_name: str,
    subject_sha256: str,
) -> MCRInTotoStatement:
    """Wrap an MCR as an unsigned in-toto v1 predicate for an artifact digest."""

    return MCRInTotoStatement.model_validate(
        {
            "_type": "https://in-toto.io/Statement/v1",
            "subject": (
                InTotoSubject(name=subject_name, digest={"sha256": subject_sha256}),
            ),
            "predicateType": MCR_PREDICATE_TYPE,
            "predicate": MCRAttestationPredicate(report=report),
        }
    )


def create_mcr_predicate(report: ModelChangeReport) -> MCRAttestationPredicate:
    """Create the predicate body expected by cosign's ``--predicate`` option."""

    return MCRAttestationPredicate(report=report)
