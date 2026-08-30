"""OCI 1.1 artifact layout for an MCR in-toto Statement referrer."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from m2riv.attestation import create_mcr_statement
from m2riv.core.models import Contract
from m2riv.reports import ModelChangeReport

OCI_IMAGE_MANIFEST_MEDIA_TYPE: Literal[
    "application/vnd.oci.image.manifest.v1+json"
] = "application/vnd.oci.image.manifest.v1+json"
OCI_IMAGE_INDEX_MEDIA_TYPE = "application/vnd.oci.image.index.v1+json"
OCI_EMPTY_CONFIG_MEDIA_TYPE = "application/vnd.oci.empty.v1+json"
MCR_OCI_ARTIFACT_TYPE: Literal[
    "application/vnd.in-toto.mcr+json"
] = "application/vnd.in-toto.mcr+json"
EMPTY_JSON_BYTES = b"{}"
EMPTY_JSON_DIGEST = (
    "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
)

OCIDigest = Annotated[str, StringConstraints(pattern=r"^sha256:[a-f0-9]{64}$")]
MediaType = Annotated[str, StringConstraints(min_length=3, max_length=255)]
AnnotationKey = Annotated[str, StringConstraints(min_length=1, max_length=255)]
AnnotationValue = Annotated[str, StringConstraints(max_length=4096)]


class OCIDescriptor(Contract):
    """Content descriptor used by OCI manifests and indexes."""

    media_type: MediaType = Field(alias="mediaType")
    digest: OCIDigest
    size: int = Field(ge=0)
    artifact_type: MediaType | None = Field(default=None, alias="artifactType")
    annotations: dict[AnnotationKey, AnnotationValue] | None = None

    @field_validator("media_type", "artifact_type")
    @classmethod
    def validate_media_type(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value != value.strip() or "/" not in value or any(
            not character.isprintable() for character in value
        ):
            raise ValueError("OCI media types must be printable type/subtype values")
        return value


class MCRArtifactManifest(Contract):
    """OCI 1.1 manifest that attaches one MCR Statement to a model subject."""

    schema_version: Literal[2] = Field(default=2, alias="schemaVersion")
    media_type: Literal["application/vnd.oci.image.manifest.v1+json"] = Field(
        default=OCI_IMAGE_MANIFEST_MEDIA_TYPE,
        alias="mediaType",
    )
    artifact_type: Literal["application/vnd.in-toto.mcr+json"] = Field(
        default=MCR_OCI_ARTIFACT_TYPE,
        alias="artifactType",
    )
    config: OCIDescriptor
    layers: tuple[OCIDescriptor, ...] = Field(min_length=1, max_length=2)
    subject: OCIDescriptor
    annotations: dict[AnnotationKey, AnnotationValue] | None = None

    @model_validator(mode="after")
    def validate_mcr_artifact_shape(self) -> MCRArtifactManifest:
        if (
            self.config.media_type != OCI_EMPTY_CONFIG_MEDIA_TYPE
            or self.config.digest != EMPTY_JSON_DIGEST
            or self.config.size != len(EMPTY_JSON_BYTES)
        ):
            raise ValueError("MCR OCI manifests require the OCI empty JSON config")
        if len(self.layers) != 1 or self.layers[0].media_type != MCR_OCI_ARTIFACT_TYPE:
            raise ValueError("MCR OCI manifests require one in-toto MCR Statement layer")
        if self.subject.artifact_type is not None:
            raise ValueError("the OCI subject descriptor must not declare artifactType")
        return self


@dataclass(frozen=True, slots=True)
class OCILayoutResult:
    """Paths and digests emitted for one local OCI image layout."""

    destination: Path
    manifest_digest: str
    statement_digest: str
    manifest: MCRArtifactManifest


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _digest(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _write_blob(root: Path, data: bytes) -> str:
    digest = _digest(data)
    target = root / "blobs" / "sha256" / digest.removeprefix("sha256:")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != data:
        raise ValueError(f"existing OCI blob does not match its digest: {target.name}")
    target.write_bytes(data)
    return digest


def create_mcr_oci_layout(
    report: ModelChangeReport,
    destination: Path,
    *,
    subject_name: str,
    subject_digest: str,
    subject_size: int,
    subject_media_type: str = OCI_IMAGE_MANIFEST_MEDIA_TYPE,
) -> OCILayoutResult:
    """Write a deterministic OCI layout containing an unsigned MCR Statement.

    The subject is an external model manifest already identified by an OCI
    descriptor. This function creates a referrer artifact; it does not upload the
    subject, sign the Statement, or authorize deployment.
    """

    if subject_size < 0:
        raise ValueError("OCI subject size must be non-negative")
    subject = OCIDescriptor.model_validate(
        {
            "mediaType": subject_media_type,
            "digest": subject_digest,
            "size": subject_size,
        }
    )
    statement = create_mcr_statement(
        report,
        subject_name=subject_name,
        subject_sha256=subject_digest.removeprefix("sha256:"),
    )
    statement_bytes = _json_bytes(
        statement.model_dump(mode="json", by_alias=True, exclude_none=True)
    )
    destination.mkdir(parents=True, exist_ok=True)
    empty_digest = _write_blob(destination, EMPTY_JSON_BYTES)
    if empty_digest != EMPTY_JSON_DIGEST:
        raise AssertionError("the OCI empty JSON descriptor constant is invalid")
    statement_digest = _write_blob(destination, statement_bytes)

    created = report.created_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    annotations = {
        "org.opencontainers.image.created": created,
        "org.opencontainers.image.description": (
            "Unsigned Model Change Report evaluation evidence; deployment authorization "
            "is consumer-side"
        ),
        "org.opencontainers.image.title": "mcr-statement.json",
    }
    manifest = MCRArtifactManifest.model_validate(
        {
            "schemaVersion": 2,
            "mediaType": OCI_IMAGE_MANIFEST_MEDIA_TYPE,
            "artifactType": MCR_OCI_ARTIFACT_TYPE,
            "config": {
                "mediaType": OCI_EMPTY_CONFIG_MEDIA_TYPE,
                "digest": EMPTY_JSON_DIGEST,
                "size": len(EMPTY_JSON_BYTES),
            },
            "layers": (
                {
                    "mediaType": MCR_OCI_ARTIFACT_TYPE,
                    "digest": statement_digest,
                    "size": len(statement_bytes),
                    "annotations": {"org.opencontainers.image.title": "mcr-statement.json"},
                },
            ),
            "subject": subject.model_dump(mode="json", by_alias=True, exclude_none=True),
            "annotations": annotations,
        }
    )
    manifest_bytes = _json_bytes(
        manifest.model_dump(mode="json", by_alias=True, exclude_none=True)
    )
    manifest_digest = _write_blob(destination, manifest_bytes)
    index = {
        "schemaVersion": 2,
        "mediaType": OCI_IMAGE_INDEX_MEDIA_TYPE,
        "manifests": [
            {
                "mediaType": OCI_IMAGE_MANIFEST_MEDIA_TYPE,
                "digest": manifest_digest,
                "size": len(manifest_bytes),
                "artifactType": MCR_OCI_ARTIFACT_TYPE,
                "annotations": annotations,
            }
        ],
    }
    (destination / "index.json").write_bytes(_json_bytes(index))
    (destination / "oci-layout").write_bytes(
        _json_bytes({"imageLayoutVersion": "1.0.0"})
    )
    return OCILayoutResult(
        destination=destination,
        manifest_digest=manifest_digest,
        statement_digest=statement_digest,
        manifest=manifest,
    )
