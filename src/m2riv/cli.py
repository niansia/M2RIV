"""Small v0.x command surface for artifact inspection and contract export."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

import typer

from m2riv import __version__
from m2riv.adapters import (
    ModelAdapter,
    OnnxRuntimeAdapter,
    OpenAICompatibleAdapter,
    OpenAICompatibleError,
    RecordedAdapter,
)
from m2riv.artifacts import (
    MAX_ARTIFACT_BYTES,
    MAX_ARTIFACT_ENTRIES,
    MAX_ARTIFACT_FILE_BYTES,
    MAX_ONNX_BYTES,
    ArtifactInspectionError,
    NumericalDiffError,
    compare_artifacts,
    compare_onnx_numerics,
    inspect_artifact,
)
from m2riv.attestation import create_mcr_predicate, create_mcr_statement
from m2riv.bisect import (
    BisectMode,
    BisectOutcome,
    BisectStatus,
    CheckpointArtifact,
    bisect_regression,
    execute_bisect,
    load_checkpoint_artifacts,
    load_checkpoint_statuses,
)
from m2riv.conformance import (
    MCRConformanceError,
    verify_consumer_conformance,
    verify_producer_conformance,
)
from m2riv.core.identity import build_local_snapshot
from m2riv.core.models import ModelFamily, RuntimeProfile
from m2riv.core.schema import export_schemas
from m2riv.demo import run_rare_slice_demo
from m2riv.engine import ObservationCache
from m2riv.gate import GateStatus
from m2riv.importers import (
    load_normalized_polygraphy,
    normalize_polygraphy_results,
    write_recorded_inputs,
)
from m2riv.io import load_policy, load_suite
from m2riv.oci import OCI_IMAGE_MANIFEST_MEDIA_TYPE, create_mcr_oci_layout
from m2riv.pipeline import ReleaseComparison, compare_exact_match
from m2riv.planning import compile_release_plan
from m2riv.plugins import builtin_metric_registry
from m2riv.reports import (
    MCRVerificationError,
    ModelChangeReport,
    ReportBundle,
    render_markdown,
    verify_report_bundle,
    write_report_bundle,
)
from m2riv.target import verify_target_evidence_manifest

app = typer.Typer(
    name="merriv",
    no_args_is_help=True,
    help='Merriv ("MEH-riv"): inspect every model change before it ships.',
)
schema_app = typer.Typer(help="Manage public Merriv contracts.")
artifact_app = typer.Typer(help="Inspect and compare deployment artifacts without inference.")
mcr_app = typer.Typer(help="Validate portable Model Change Report bundles.")
conformance_app = typer.Typer(
    help="Test independent Model Change Report producers and consumers."
)
import_app = typer.Typer(
    help="Translate retained external-tool evidence into Model Change Report inputs."
)
app.add_typer(schema_app, name="schema")
app.add_typer(artifact_app, name="artifact")
app.add_typer(mcr_app, name="mcr")
app.add_typer(conformance_app, name="conformance")
app.add_typer(import_app, name="import")


class BisectAdapterKind(StrEnum):
    RECORDED = "recorded"
    ONNX = "onnx"


class OnnxOutputMode(StrEnum):
    IDENTITY = "identity"
    ARGMAX = "argmax"


class PolygraphySourceFormat(StrEnum):
    NATIVE = "native"
    NORMALIZED = "normalized"


@app.command()
def version() -> None:
    """Print the installed Merriv version."""
    typer.echo(__version__)


@mcr_app.command("verify")
def mcr_verify_command(
    source: Annotated[Path, typer.Argument(exists=True, readable=True)],
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Fail when any linked evidence cannot be rehashed."),
    ] = False,
) -> None:
    """Verify Model Change Report identities, manifests, and linked evidence."""
    try:
        result = verify_report_bundle(source, require_complete=strict)
    except (OSError, MCRVerificationError) as error:
        typer.echo(json.dumps({"valid": False, "error": str(error)}, indent=2))
        raise typer.Exit(code=3) from error
    typer.echo(result.model_dump_json(indent=2))


@mcr_app.command("verify-target")
def mcr_verify_target_command(
    source: Annotated[Path, typer.Argument(exists=True, readable=True)],
) -> None:
    """Verify a target evidence root, every retained file, and every report bundle."""
    try:
        result = verify_target_evidence_manifest(source)
    except (OSError, MCRVerificationError) as error:
        typer.echo(json.dumps({"valid": False, "error": str(error)}, indent=2))
        raise typer.Exit(code=3) from error
    typer.echo(result.model_dump_json(indent=2))


@mcr_app.command("predicate")
def mcr_predicate_command(
    source: Annotated[Path, typer.Argument(exists=True, readable=True)],
) -> None:
    """Emit a Model Change Report predicate for an in-toto attestor."""
    try:
        predicate = create_mcr_predicate(_load_strict_mcr(source))
    except (OSError, ValueError, MCRVerificationError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        raise typer.Exit(code=3) from error
    typer.echo(predicate.model_dump_json(indent=2))


def _load_strict_mcr(source: Path) -> ModelChangeReport:
    verify_report_bundle(source, require_complete=True)
    report_path = source / "mcr-report.json" if source.is_dir() else source
    return ModelChangeReport.model_validate_json(report_path.read_text("utf-8"))


@mcr_app.command("statement")
def mcr_statement_command(
    source: Annotated[Path, typer.Argument(exists=True, readable=True)],
    subject_name: Annotated[str, typer.Option("--subject-name")],
    subject_sha256: Annotated[str, typer.Option("--subject-sha256")],
) -> None:
    """Emit an unsigned in-toto v1 Statement bound to an artifact digest."""

    try:
        report = _load_strict_mcr(source)
        statement = create_mcr_statement(
            report,
            subject_name=subject_name,
            subject_sha256=subject_sha256,
        )
    except (OSError, ValueError, MCRVerificationError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        raise typer.Exit(code=3) from error
    typer.echo(statement.model_dump_json(indent=2, by_alias=True))


@mcr_app.command("oci-layout")
def mcr_oci_layout_command(
    source: Annotated[Path, typer.Argument(exists=True, readable=True)],
    subject_name: Annotated[str, typer.Option("--subject-name")],
    subject_digest: Annotated[str, typer.Option("--subject-digest")],
    subject_size: Annotated[int, typer.Option("--subject-size", min=0)],
    destination: Annotated[Path, typer.Option("--output", "-o")],
    subject_media_type: Annotated[
        str,
        typer.Option("--subject-media-type"),
    ] = OCI_IMAGE_MANIFEST_MEDIA_TYPE,
) -> None:
    """Build an OCI 1.1 layout with an unsigned report Statement referrer."""

    try:
        report = _load_strict_mcr(source)
        result = create_mcr_oci_layout(
            report,
            destination,
            subject_name=subject_name,
            subject_digest=subject_digest,
            subject_size=subject_size,
            subject_media_type=subject_media_type,
        )
    except (OSError, ValueError, MCRVerificationError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        raise typer.Exit(code=3) from error
    typer.echo(
        json.dumps(
            {
                "oci_layout": str(result.destination),
                "manifest_digest": result.manifest_digest,
                "statement_digest": result.statement_digest,
                "artifact_type": result.manifest.artifact_type,
                "deployment_authorization": "not-evaluated",
            },
            indent=2,
            sort_keys=True,
        )
    )


@conformance_app.command("producer")
def conformance_producer_command(
    source: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
) -> None:
    """Verify fixed decision-state and must-reject producer conformance vectors."""
    try:
        result = verify_producer_conformance(source)
    except (OSError, MCRConformanceError) as error:
        typer.echo(json.dumps({"conformant": False, "error": str(error)}, indent=2))
        raise typer.Exit(code=3) from error
    typer.echo(result.model_dump_json(indent=2))


@conformance_app.command("consumer")
def conformance_consumer_command(
    receipt: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    fixtures: Annotated[
        Path,
        typer.Option(
            "--fixtures",
            exists=True,
            file_okay=False,
            readable=True,
            help="Normative five-state producer fixture directory.",
        ),
    ] = Path("examples/mcr_conformance"),
) -> None:
    """Verify a consumer receipt and fail-closed decision interpretation."""
    try:
        result = verify_consumer_conformance(receipt, fixtures=fixtures)
    except (OSError, MCRConformanceError) as error:
        typer.echo(json.dumps({"conformant": False, "error": str(error)}, indent=2))
        raise typer.Exit(code=3) from error
    typer.echo(result.model_dump_json(indent=2))


@app.command()
def inspect(
    artifact: Annotated[Path, typer.Argument(exists=True, readable=True)],
    family: Annotated[ModelFamily, typer.Option()] = ModelFamily.CUSTOM,
    max_artifact_bytes: Annotated[int, typer.Option(min=1)] = MAX_ARTIFACT_BYTES,
    max_artifact_file_bytes: Annotated[int, typer.Option(min=1)] = MAX_ARTIFACT_FILE_BYTES,
    max_artifact_entries: Annotated[int, typer.Option(min=1)] = MAX_ARTIFACT_ENTRIES,
) -> None:
    """Resolve a local artifact into a content-addressed model snapshot."""
    try:
        snapshot = build_local_snapshot(
            artifact,
            model_family=family,
            max_artifact_bytes=max_artifact_bytes,
            max_artifact_file_bytes=max_artifact_file_bytes,
            max_artifact_entries=max_artifact_entries,
        )
    except (OSError, ValueError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        raise typer.Exit(code=3) from error
    typer.echo(snapshot.model_dump_json(indent=2))


@artifact_app.command("inspect")
def artifact_inspect_command(
    artifact: Annotated[Path, typer.Argument(exists=True, readable=True)],
    max_onnx_bytes: Annotated[
        int, typer.Option(min=1, max=16 * 1024 * 1024 * 1024)
    ] = MAX_ONNX_BYTES,
    max_artifact_bytes: Annotated[int, typer.Option(min=1)] = MAX_ARTIFACT_BYTES,
    max_artifact_file_bytes: Annotated[int, typer.Option(min=1)] = MAX_ARTIFACT_FILE_BYTES,
    max_artifact_entries: Annotated[int, typer.Option(min=1)] = MAX_ARTIFACT_ENTRIES,
) -> None:
    """Describe ONNX structure, dtypes, operators, interfaces, and sidecars."""
    try:
        profile = inspect_artifact(
            artifact,
            max_onnx_bytes=max_onnx_bytes,
            max_artifact_bytes=max_artifact_bytes,
            max_artifact_file_bytes=max_artifact_file_bytes,
            max_artifact_entries=max_artifact_entries,
        )
    except (ArtifactInspectionError, OSError, ValueError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        raise typer.Exit(code=3) from error
    typer.echo(profile.model_dump_json(indent=2))


@artifact_app.command("diff")
def artifact_diff_command(
    baseline: Annotated[Path, typer.Argument(exists=True, readable=True)],
    candidate: Annotated[Path, typer.Argument(exists=True, readable=True)],
    max_onnx_bytes: Annotated[
        int, typer.Option(min=1, max=16 * 1024 * 1024 * 1024)
    ] = MAX_ONNX_BYTES,
    max_artifact_bytes: Annotated[int, typer.Option(min=1)] = MAX_ARTIFACT_BYTES,
    max_artifact_file_bytes: Annotated[int, typer.Option(min=1)] = MAX_ARTIFACT_FILE_BYTES,
    max_artifact_entries: Annotated[int, typer.Option(min=1)] = MAX_ARTIFACT_ENTRIES,
) -> None:
    """Compare artifact structure before paying inference cost."""
    try:
        diff = compare_artifacts(
            inspect_artifact(
                baseline,
                max_onnx_bytes=max_onnx_bytes,
                max_artifact_bytes=max_artifact_bytes,
                max_artifact_file_bytes=max_artifact_file_bytes,
                max_artifact_entries=max_artifact_entries,
            ),
            inspect_artifact(
                candidate,
                max_onnx_bytes=max_onnx_bytes,
                max_artifact_bytes=max_artifact_bytes,
                max_artifact_file_bytes=max_artifact_file_bytes,
                max_artifact_entries=max_artifact_entries,
            ),
        )
    except (ArtifactInspectionError, OSError, ValueError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        raise typer.Exit(code=3) from error
    typer.echo(diff.model_dump_json(indent=2))


@artifact_app.command("numerical-diff")
def artifact_numerical_diff_command(
    baseline: Annotated[Path, typer.Argument(exists=True, readable=True)],
    candidate: Annotated[Path, typer.Argument(exists=True, readable=True)],
    suite: Annotated[Path, typer.Option("--suite", exists=True, readable=True)],
    absolute_tolerance: Annotated[float, typer.Option("--atol", min=0)] = 1e-5,
    relative_tolerance: Annotated[float, typer.Option("--rtol", min=0)] = 1e-4,
    max_cases: Annotated[int, typer.Option("--max-cases", min=1, max=128)] = 128,
) -> None:
    """Execute a bounded suite prefix and report the first numerical divergence."""
    try:
        cases = load_suite(suite)
        result = compare_onnx_numerics(
            baseline,
            candidate,
            cases[:max_cases],
            absolute_tolerance=absolute_tolerance,
            relative_tolerance=relative_tolerance,
        )
    except (NumericalDiffError, OSError, ValueError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        raise typer.Exit(code=3) from error
    typer.echo(result.model_dump_json(indent=2))


def _print_comparison(result: ReleaseComparison, bundle: ReportBundle) -> None:
    typer.echo("MODEL CHANGE SUMMARY")
    for metric in result.report.metrics:
        metric_id = "".join(
            "?" if ord(character) < 32 or 127 <= ord(character) < 160 else character
            for character in metric.metric_id
        )
        delta = (
            f"{metric.delta:+.1%}"
            if metric.unit == "ratio"
            else f"{metric.delta:+.3f} {metric.unit}"
        )
        typer.echo(f"{metric_id:<32} {delta}  n={metric.sample_size}")
    typer.echo(f"EVALUATION DECISION: {result.report.decision.status.value}")
    typer.echo(
        "EVALUATION POLICY SATISFIED: "
        f"{str(result.report.decision.evaluation_policy_satisfied).lower()}"
    )
    typer.echo("DEPLOYMENT AUTHORIZATION: NOT EVALUATED (consumer-side)")
    typer.echo(f"REPORT: {bundle.markdown_path}")


def _write_github_summary(result: ReleaseComparison) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    try:
        with Path(summary_path).open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(render_markdown(result.report))
    except OSError:
        typer.echo("WARN: could not write GitHub Step Summary", err=True)


def _raise_for_evaluation_decision(result: ReleaseComparison) -> None:
    """Map an unsatisfied evaluation policy to a stable CI exit code."""
    if result.report.decision.evaluation_policy_satisfied:
        return
    if result.gate.status is GateStatus.BLOCK:
        raise typer.Exit(code=2)
    if result.gate.status is GateStatus.ERROR:
        raise typer.Exit(code=3)
    if result.gate.status is GateStatus.WARN:
        raise typer.Exit(code=4)
    if result.gate.status is GateStatus.INSUFFICIENT_POWER:
        raise typer.Exit(code=4)
    raise typer.Exit(code=3)


def _run_recorded_comparison(
    *,
    baseline: Path,
    candidate: Path,
    suite: Path,
    policy: Path,
    destination: Path,
    slice_keys: tuple[str, ...],
    family: ModelFamily,
    resamples: int,
    confidence_level: float,
) -> tuple[ReleaseComparison, ReportBundle]:
    cases = load_suite(suite)
    gate_policy = load_policy(policy)
    baseline_snapshot = build_local_snapshot(
        baseline,
        model_family=family,
        execution_config={"adapter": "recorded-output-v1"},
        labels={"role": "baseline"},
    )
    candidate_snapshot = build_local_snapshot(
        candidate,
        model_family=family,
        execution_config={"adapter": "recorded-output-v1"},
        labels={"role": "candidate"},
    )
    result = compare_exact_match(
        baseline=RecordedAdapter.from_jsonl(baseline, baseline_snapshot),
        candidate=RecordedAdapter.from_jsonl(candidate, candidate_snapshot),
        cases=cases,
        policy=gate_policy,
        cache=ObservationCache(destination / ".cache"),
        profile=RuntimeProfile(seed=0),
        slice_keys=slice_keys,
        baseline_adapter_fingerprint="m2riv.recorded@1",
        candidate_adapter_fingerprint="m2riv.recorded@1",
        resamples=resamples,
        confidence_level=confidence_level,
    )
    bundle = write_report_bundle(
        result.report,
        destination,
        release_plan=result.plan,
        evidence_manifest=result.evidence_manifest,
    )
    return result, bundle


def _finish_comparison(result: ReleaseComparison, bundle: ReportBundle) -> None:
    _print_comparison(result, bundle)
    _write_github_summary(result)
    _raise_for_evaluation_decision(result)


@app.command("compare")
def compare_command(
    baseline: Annotated[Path, typer.Argument(exists=True, readable=True)],
    candidate: Annotated[Path, typer.Argument(exists=True, readable=True)],
    suite: Annotated[Path, typer.Option("--suite", exists=True, readable=True)],
    policy: Annotated[Path, typer.Option("--policy", exists=True, readable=True)],
    destination: Annotated[Path, typer.Option("--output", "-o")] = Path("runs/compare"),
    slice_key: Annotated[list[str] | None, typer.Option("--slice-key")] = None,
    family: Annotated[ModelFamily, typer.Option()] = ModelFamily.CUSTOM,
    resamples: Annotated[int, typer.Option(min=100)] = 2_000,
    confidence_level: Annotated[float, typer.Option(min=0.000001, max=0.999999)] = 0.95,
) -> None:
    """Compare two recorded-output JSONL artifacts and apply an evaluation policy."""

    try:
        result, bundle = _run_recorded_comparison(
            baseline=baseline,
            candidate=candidate,
            suite=suite,
            policy=policy,
            destination=destination,
            slice_keys=tuple(slice_key or ()),
            family=family,
            resamples=resamples,
            confidence_level=confidence_level,
        )
    except (OSError, OpenAICompatibleError, ValueError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        raise typer.Exit(code=3) from error
    _finish_comparison(result, bundle)


@import_app.command("polygraphy")
def import_polygraphy_command(
    source: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    policy: Annotated[Path, typer.Option("--policy", exists=True, readable=True)],
    destination: Annotated[Path, typer.Option("--output", "-o")] = Path(
        "runs/polygraphy-import"
    ),
    source_format: Annotated[PolygraphySourceFormat, typer.Option("--format")] = (
        PolygraphySourceFormat.NATIVE
    ),
    baseline_runner: Annotated[str, typer.Option("--baseline-runner")] = "onnxrt-runner",
    candidate_runner: Annotated[str, typer.Option("--candidate-runner")] = "trt-runner",
    absolute_tolerance: Annotated[float, typer.Option("--atol", min=0)] = 1e-5,
    relative_tolerance: Annotated[float, typer.Option("--rtol", min=0)] = 1e-5,
    translate_only: Annotated[bool, typer.Option("--translate-only")] = False,
    resamples: Annotated[int, typer.Option(min=100)] = 2_000,
    confidence_level: Annotated[float, typer.Option(min=0.000001, max=0.999999)] = 0.95,
) -> None:
    """Import retained Polygraphy results and produce a Model Change Report."""

    try:
        if source_format is PolygraphySourceFormat.NORMALIZED:
            payload = load_normalized_polygraphy(source)
        else:
            payload = normalize_polygraphy_results(
                source,
                baseline_runner=baseline_runner,
                candidate_runner=candidate_runner,
                absolute_tolerance=absolute_tolerance,
                relative_tolerance=relative_tolerance,
            )
        translated = destination / "translated"
        baseline, candidate, suite = write_recorded_inputs(payload, translated)
        if translate_only:
            typer.echo(str(translated))
            return
        result, bundle = _run_recorded_comparison(
            baseline=baseline,
            candidate=candidate,
            suite=suite,
            policy=policy,
            destination=destination,
            slice_keys=(),
            family=ModelFamily.CUSTOM,
            resamples=resamples,
            confidence_level=confidence_level,
        )
    except (OSError, RuntimeError, ValueError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        raise typer.Exit(code=3) from error
    if source_format is PolygraphySourceFormat.NORMALIZED:
        typer.echo("SOURCE TRUST: normalized interchange (not live TensorRT evidence)")
    _finish_comparison(result, bundle)


@app.command("plan")
def plan_command(
    suite: Annotated[Path, typer.Option("--suite", exists=True, readable=True)],
    policy: Annotated[Path, typer.Option("--policy", exists=True, readable=True)],
    slice_key: Annotated[list[str] | None, typer.Option("--slice-key")] = None,
    seed: Annotated[int, typer.Option()] = 0,
    resamples: Annotated[int, typer.Option(min=1)] = 2_000,
    confidence_level: Annotated[float, typer.Option(min=0.000001, max=0.999999)] = 0.95,
) -> None:
    """Compile policy, suite, and built-in metrics without running inference."""
    try:
        registry = builtin_metric_registry()
        release_plan = compile_release_plan(
            policy=load_policy(policy),
            cases=load_suite(suite),
            metrics=registry.metrics(),
            slice_keys=tuple(slice_key or ()),
            metric_plugins=registry.metric_plugin_records(),
            runtime_profile=RuntimeProfile(seed=seed),
            resamples=resamples,
            confidence_level=confidence_level,
        )
    except (OSError, ValueError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        raise typer.Exit(code=3) from error
    typer.echo(release_plan.model_dump_json(indent=2))


@app.command("compare-api")
def compare_api_command(
    baseline_endpoint: Annotated[str, typer.Argument()],
    candidate_endpoint: Annotated[str, typer.Argument()],
    baseline_model: Annotated[str, typer.Option("--baseline-model")],
    candidate_model: Annotated[str, typer.Option("--candidate-model")],
    suite: Annotated[Path, typer.Option("--suite", exists=True, readable=True)],
    policy: Annotated[Path, typer.Option("--policy", exists=True, readable=True)],
    destination: Annotated[Path, typer.Option("--output", "-o")] = Path("runs/api-compare"),
    slice_key: Annotated[list[str] | None, typer.Option("--slice-key")] = None,
    baseline_api_key_env: Annotated[str, typer.Option()] = "MERRIV_BASELINE_API_KEY",
    candidate_api_key_env: Annotated[str, typer.Option()] = "MERRIV_CANDIDATE_API_KEY",
    baseline_credential_scope: Annotated[str, typer.Option()] = "baseline",
    candidate_credential_scope: Annotated[str, typer.Option()] = "candidate",
    baseline_revision: Annotated[str | None, typer.Option()] = None,
    candidate_revision: Annotated[str | None, typer.Option()] = None,
    timeout_s: Annotated[float, typer.Option(min=0.1, max=300.0)] = 30.0,
    max_elapsed_s: Annotated[float, typer.Option(min=0.1, max=3_600.0)] = 120.0,
    max_response_bytes: Annotated[int, typer.Option(min=1, max=100 * 1024 * 1024)] = 10
    * 1024
    * 1024,
    max_retries: Annotated[int, typer.Option(min=0, max=5)] = 1,
    resamples: Annotated[int, typer.Option(min=100)] = 2_000,
    confidence_level: Annotated[float, typer.Option(min=0.000001, max=0.999999)] = 0.95,
) -> None:
    """Compare two OpenAI-compatible chat-completions endpoints."""
    try:
        cases = load_suite(suite)
        gate_policy = load_policy(policy)
        baseline_adapter = OpenAICompatibleAdapter(
            baseline_endpoint,
            baseline_model,
            api_key=os.environ.get(baseline_api_key_env),
            credential_scope=baseline_credential_scope,
            deployment_revision=baseline_revision,
            timeout_s=timeout_s,
            max_elapsed_s=max_elapsed_s,
            max_response_bytes=max_response_bytes,
            max_retries=max_retries,
        )
        candidate_adapter = OpenAICompatibleAdapter(
            candidate_endpoint,
            candidate_model,
            api_key=os.environ.get(candidate_api_key_env),
            credential_scope=candidate_credential_scope,
            deployment_revision=candidate_revision,
            timeout_s=timeout_s,
            max_elapsed_s=max_elapsed_s,
            max_response_bytes=max_response_bytes,
            max_retries=max_retries,
        )
        with tempfile.TemporaryDirectory(prefix="m2riv-api-cache-") as cache_root:
            result = compare_exact_match(
                baseline=baseline_adapter,
                candidate=candidate_adapter,
                cases=cases,
                policy=gate_policy,
                cache=ObservationCache(cache_root),
                profile=RuntimeProfile(seed=0),
                slice_keys=tuple(slice_key or ()),
                baseline_adapter_fingerprint=(f"baseline:{baseline_adapter.adapter_fingerprint}"),
                candidate_adapter_fingerprint=(
                    f"candidate:{candidate_adapter.adapter_fingerprint}"
                ),
                resamples=resamples,
                confidence_level=confidence_level,
            )
            bundle = write_report_bundle(
                result.report,
                destination,
                release_plan=result.plan,
                evidence_manifest=result.evidence_manifest,
            )
    except (OSError, OpenAICompatibleError, ValueError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        raise typer.Exit(code=3) from error

    _print_comparison(result, bundle)
    _write_github_summary(result)
    _raise_for_evaluation_decision(result)


@app.command("bisect")
def bisect_command(
    manifest: Annotated[Path, typer.Argument(exists=True, readable=True)],
    mode: Annotated[BisectMode, typer.Option()] = BisectMode.MONOTONIC,
    sparse_points: Annotated[int, typer.Option(min=2)] = 7,
) -> None:
    """Locate a regression from an ordered checkpoint-status JSONL manifest."""
    try:
        records = load_checkpoint_statuses(manifest)
        effective_mode = mode
        if mode is not BisectMode.LINEAR_AUDIT:
            statuses = tuple(record.status for record in records)
            has_uncertain = any(
                status in {BisectStatus.WARN, BisectStatus.ERROR} for status in statuses
            )
            seen_block = False
            has_reversal = False
            for status in statuses:
                if status is BisectStatus.BLOCK:
                    seen_block = True
                elif status is BisectStatus.PASS and seen_block:
                    has_reversal = True
                    break
            if has_uncertain or has_reversal:
                # Every manifest row is already observed evidence. Do not let a
                # binary callback schedule hide a known uncertainty or reversal.
                effective_mode = BisectMode.LINEAR_AUDIT
        result = bisect_regression(
            len(records),
            lambda index: records[index].status,
            mode=effective_mode,
            sparse_points=sparse_points,
        )
    except (OSError, ValueError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        raise typer.Exit(code=3) from error

    payload = asdict(result)
    payload["requested_mode"] = mode.value
    payload["effective_mode"] = effective_mode.value
    if result.outcome is BisectOutcome.NON_MONOTONIC and mode is not BisectMode.LINEAR_AUDIT:
        payload["audit_confidence"] = payload["confidence"]
        payload["confidence"] = "none"
    payload["first_failing_checkpoint"] = (
        records[result.first_failing_index].checkpoint
        if result.first_failing_index is not None
        else None
    )
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    if result.outcome is BisectOutcome.INCONCLUSIVE:
        raise typer.Exit(code=3)
    if result.outcome in {
        BisectOutcome.FIRST_FAILING,
        BisectOutcome.REGRESSION_BOUNDED,
        BisectOutcome.NON_MONOTONIC,
    }:
        raise typer.Exit(code=2)


@app.command("bisect-run")
def bisect_run_command(
    manifest: Annotated[Path, typer.Argument(exists=True, readable=True)],
    suite: Annotated[Path, typer.Option("--suite", exists=True, readable=True)],
    policy: Annotated[Path, typer.Option("--policy", exists=True, readable=True)],
    destination: Annotated[Path, typer.Option("--output", "-o")] = Path("runs/bisect-run"),
    adapter_kind: Annotated[BisectAdapterKind, typer.Option("--adapter")] = (
        BisectAdapterKind.RECORDED
    ),
    mode: Annotated[BisectMode, typer.Option()] = BisectMode.MONOTONIC,
    sparse_points: Annotated[int, typer.Option(min=2)] = 7,
    slice_key: Annotated[list[str] | None, typer.Option("--slice-key")] = None,
    family: Annotated[ModelFamily, typer.Option()] = ModelFamily.CUSTOM,
    onnx_output_mode: Annotated[OnnxOutputMode, typer.Option()] = OnnxOutputMode.IDENTITY,
    resamples: Annotated[int, typer.Option(min=100)] = 2_000,
    confidence_level: Annotated[float, typer.Option(min=0.000001, max=0.999999)] = 0.95,
) -> None:
    """Execute and gate checkpoints selected by the bisect strategy."""
    try:
        records = load_checkpoint_artifacts(manifest)
        cases = load_suite(suite)
        gate_policy = load_policy(policy)

        def adapter_factory(
            record: CheckpointArtifact, role: Literal["baseline", "candidate"]
        ) -> tuple[ModelAdapter, str]:
            if adapter_kind is BisectAdapterKind.ONNX:
                onnx_adapter = OnnxRuntimeAdapter(
                    record.artifact,
                    model_family=family,
                    output_mode=onnx_output_mode.value,
                )
                return onnx_adapter, f"m2riv.onnxruntime:{onnx_adapter.adapter_fingerprint}"
            snapshot = build_local_snapshot(
                record.artifact,
                model_family=family,
                execution_config={"adapter": "recorded-output-v1"},
                labels={"checkpoint": record.checkpoint, "role": role},
            )
            return (
                RecordedAdapter.from_jsonl(record.artifact, snapshot),
                "m2riv.recorded@1",
            )

        execution = execute_bisect(
            records,
            adapter_factory=adapter_factory,
            cases=cases,
            policy=gate_policy,
            cache=ObservationCache(destination / ".cache"),
            destination=destination,
            profile=RuntimeProfile(
                seed=0,
                device="cpu" if adapter_kind is BisectAdapterKind.ONNX else None,
            ),
            slice_keys=tuple(slice_key or ()),
            mode=mode,
            sparse_points=sparse_points,
            resamples=resamples,
            confidence_level=confidence_level,
        )
    except (OSError, ValueError) as error:
        typer.echo(f"ERROR: {error}", err=True)
        raise typer.Exit(code=3) from error

    payload = asdict(execution.result)
    payload["first_failing_checkpoint"] = (
        records[execution.result.first_failing_index].checkpoint
        if execution.result.first_failing_index is not None
        else None
    )
    payload["adapter"] = adapter_kind.value
    payload["executed_checkpoints"] = [
        {
            "index": item.index,
            "checkpoint": item.checkpoint,
            "artifact": item.artifact.as_posix(),
            "status": item.status.value,
            "report_id": item.report_id,
            "report_directory": item.report_directory.as_posix(),
        }
        for item in execution.checkpoints
    ]
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "bisect-result.json").write_text(rendered, encoding="utf-8")
    typer.echo(rendered, nl=False)
    if execution.result.outcome is BisectOutcome.INCONCLUSIVE:
        raise typer.Exit(code=3)
    if execution.result.outcome in {
        BisectOutcome.FIRST_FAILING,
        BisectOutcome.REGRESSION_BOUNDED,
        BisectOutcome.NON_MONOTONIC,
    }:
        raise typer.Exit(code=2)


@app.command()
def demo(
    destination: Annotated[Path, typer.Option("--output", "-o")] = Path("runs/demo"),
) -> None:
    """Run the offline rare-slice regression demo."""
    result = run_rare_slice_demo(destination)
    _print_comparison(result.comparison, result.bundle)
    typer.echo(f"CACHE: {result.warm_cache_hits} observations reused")


@schema_app.command("export")
def schema_export(
    destination: Annotated[Path, typer.Argument()] = Path("schemas/mcr-0.4"),
) -> None:
    """Export versioned JSON Schemas for cross-language consumers."""
    paths = export_schemas(destination)
    typer.echo(f"Exported {len(paths)} public schemas to {destination}")


if __name__ == "__main__":
    app()
