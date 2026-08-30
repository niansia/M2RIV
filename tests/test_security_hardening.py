from __future__ import annotations

import json
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from merriv.adapters import (
    AdapterCapability,
    FakeAdapter,
    OpenAICompatibleAdapter,
    OpenAICompatibleError,
)
from merriv.cli import app
from merriv.core.identity import (
    build_local_snapshot,
    fingerprint,
    observation_content_id,
    read_verified_file,
)
from merriv.core.models import EvalCase, ModelSnapshot, Observation, RuntimeProfile
from merriv.engine import CACHE_KEY_ENV, CacheKey, ObservationCache, PairedRunner
from merriv.engine.runner import RunnerContractError
from merriv.reports import MCRVerificationError, verify_report_bundle, write_report_bundle
from merriv.reports.models import MCRDecision, MCRStatus, create_report


def _cache_record() -> tuple[CacheKey, Observation]:
    snapshot_id = f"mcr:sha256:{'1' * 64}"
    case = EvalCase(case_id="security-case", input="request")
    profile = RuntimeProfile(seed=17)
    output = "blocked-output"
    output_digest = fingerprint(output, namespace="observation-output")
    observation = Observation(
        id=observation_content_id(
            snapshot_id=snapshot_id,
            case_id=case.case_id,
            seed=profile.seed,
            output_digest=output_digest,
        ),
        snapshot_id=snapshot_id,
        case_id=case.case_id,
        seed=profile.seed,
        output=output,
        output_digest=output_digest,
    )
    key = CacheKey.for_case(
        snapshot_id=snapshot_id,
        case=case,
        runtime_profile=profile,
        adapter_fingerprint="security-adapter-v1",
    )
    return key, observation


def _minimal_report():
    return create_report(
        baseline_snapshot_id=f"mcr:sha256:{'2' * 64}",
        candidate_snapshot_id=f"mcr:sha256:{'3' * 64}",
        metrics=(),
        decision=MCRDecision(status=MCRStatus.PASS, allowed=True),
    )


@pytest.mark.parametrize(
    "case_id",
    [
        "nul\x00id",
        "ansi\x1b[31m",
        "line\nbreak",
        "right-to-left\u202eoverride",
        "x" * 257,
        " leading",
        "trailing ",
    ],
)
def test_case_ids_reject_control_bidi_and_ambiguous_values(case_id: str) -> None:
    with pytest.raises(ValueError, match=r"case_id|256"):
        EvalCase(case_id=case_id, input="value")


def test_deep_yaml_is_a_clean_cli_error_without_traceback(tmp_path: Path) -> None:
    suite = tmp_path / "suite.jsonl"
    suite.write_text('{"case_id":"one","input":"x"}\n', encoding="utf-8")
    policy = tmp_path / "policy.yaml"
    policy.write_text("value: " + "[" * 2_000 + "0" + "]" * 2_000, encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["plan", "--suite", str(suite), "--policy", str(policy)],
    )

    assert result.exit_code == 3
    rendered = result.stdout + result.stderr
    assert "Traceback" not in rendered
    assert "invalid policy YAML" in rendered


def test_public_fingerprints_cannot_resign_a_poisoned_cache_entry(tmp_path: Path) -> None:
    key, observation = _cache_record()
    cache = ObservationCache(tmp_path / "cache")
    cache.put(key, observation)
    path = cache.path_for(key)
    envelope = json.loads(path.read_text("utf-8"))
    poisoned_output = "pass-output"
    poisoned_digest = fingerprint(poisoned_output, namespace="observation-output")
    envelope["observation"]["output"] = poisoned_output
    envelope["observation"]["output_digest"] = poisoned_digest
    envelope["observation"]["id"] = observation_content_id(
        snapshot_id=observation.snapshot_id,
        case_id=observation.case_id,
        seed=observation.seed,
        output_digest=poisoned_digest,
    )
    path.write_text(json.dumps(envelope), encoding="utf-8")

    assert cache.get(key) is None


def test_default_cache_is_process_local_but_shared_hmac_cache_is_reusable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key, observation = _cache_record()
    local_root = tmp_path / "local"
    first_local = ObservationCache(local_root)
    first_local.put(key, observation)
    assert first_local.get(key) == observation
    assert ObservationCache(local_root).get(key) == observation

    # A fresh process receives a new ephemeral key and treats previous entries as
    # misses. Replacing the private module key models that process boundary without
    # transferring any secret into a child command line or environment.
    monkeypatch.setattr("merriv.engine.cache._PROCESS_LOCAL_KEY_MATERIAL", secrets.token_bytes(32))
    assert ObservationCache(local_root).get(key) is None

    shared_root = tmp_path / "shared"
    shared_key = b"k" * 32
    first_shared = ObservationCache(shared_root, authentication_key=shared_key)
    first_shared.put(key, observation)
    assert ObservationCache(shared_root, authentication_key=shared_key).get(key) == observation
    assert b"k" * 32 not in first_shared.path_for(key).read_bytes()


def test_short_environment_cache_key_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CACHE_KEY_ENV, "too-short")
    with pytest.raises(ValueError, match="at least 32 bytes"):
        ObservationCache(tmp_path / "cache")


@dataclass
class _ForgingAdapter:
    snapshot: ModelSnapshot
    reported_seed: int

    def describe(self) -> ModelSnapshot:
        return self.snapshot

    def capabilities(self) -> frozenset[AdapterCapability]:
        return frozenset()

    def run(self, cases: Sequence[EvalCase], profile: RuntimeProfile) -> tuple[Observation, ...]:
        output = "answer"
        digest = fingerprint(output, namespace="observation-output")
        return tuple(
            Observation(
                id=f"mcr:sha256:{'f' * 64}",
                snapshot_id=self.snapshot.id,
                case_id=case.case_id,
                seed=self.reported_seed,
                output=output,
                output_digest=digest,
            )
            for case in cases
        )


def test_runner_owns_observation_identity_and_rejects_forged_seed(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.bin"
    candidate_path = tmp_path / "candidate.bin"
    baseline_path.write_bytes(b"baseline")
    candidate_path.write_bytes(b"candidate")
    baseline_snapshot = build_local_snapshot(baseline_path)
    candidate_snapshot = build_local_snapshot(candidate_path)
    profile = RuntimeProfile(seed=23)
    case = EvalCase(case_id="one", input="hello")
    candidate = FakeAdapter(candidate_snapshot, responses={"one": "answer"})

    run = PairedRunner(ObservationCache(tmp_path / "canonical-cache")).run(
        _ForgingAdapter(baseline_snapshot, profile.seed),
        candidate,
        (case,),
        profile=profile,
        baseline_adapter_fingerprint="forging-v1",
        candidate_adapter_fingerprint="candidate-v1",
    )
    assert run.cases[0].baseline.id != f"mcr:sha256:{'f' * 64}"

    with pytest.raises(RunnerContractError, match="wrong seed"):
        PairedRunner(ObservationCache(tmp_path / "wrong-seed-cache")).run(
            _ForgingAdapter(baseline_snapshot, profile.seed + 1),
            candidate,
            (case,),
            profile=profile,
            baseline_adapter_fingerprint="forging-v1",
            candidate_adapter_fingerprint="candidate-v1",
        )


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://169.254.169.254/v1",
        "http://2852039166/v1",
        "http://0xA9FEA9FE/v1",
        "http://0251.0376.0251.0376/v1",
        "http://169.254.43518/v1",
        "http://metadata.google.internal/v1",
        "http://metadata.google.internal./v1",
        "http://instance-data.ec2.internal/v1",
        "http://[fe80::1]/v1",
        "http://[::ffff:169.254.169.254]/v1",
        "http://[fd00:ec2::254]/v1",
        "http://100.100.100.200/v1",
        "http://1684301000/v1",
        "http://0x646464C8/v1",
        "http://0144.0144.0144.0310/v1",
        "http://100.100.25800/v1",
        "http://[::ffff:100.100.100.200]/v1",
    ],
)
def test_metadata_endpoints_are_rejected(endpoint: str) -> None:
    with pytest.raises(ValueError, match=r"metadata|link-local|valid HTTP"):
        OpenAICompatibleAdapter(endpoint, "model")


def test_private_model_endpoints_remain_supported_and_keys_require_tls() -> None:
    OpenAICompatibleAdapter("http://127.0.0.1:8000/v1", "model")
    OpenAICompatibleAdapter("http://10.0.0.8:8000/v1", "model")
    with pytest.raises(ValueError, match="HTTPS"):
        OpenAICompatibleAdapter("http://10.0.0.8:8000/v1", "model", api_key="secret")
    OpenAICompatibleAdapter(
        "http://10.0.0.8:8000/v1",
        "model",
        api_key="secret",
        allow_insecure_http=True,
    )


def test_redirecting_custom_client_and_duplicate_response_keys_fail_closed() -> None:
    client = httpx.Client(follow_redirects=True)
    try:
        with pytest.raises(ValueError, match="redirect"):
            OpenAICompatibleAdapter("https://example.test/v1", "model", client=client)
    finally:
        client.close()

    adapter = OpenAICompatibleAdapter(
        "https://example.test/v1",
        "model",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                content=(
                    b'{"choices":[{"message":{"content":"safe"}}],'
                    b'"choices":[{"message":{"content":"forged"}}]}'
                ),
            )
        ),
    )
    with pytest.raises(OpenAICompatibleError, match="invalid JSON"):
        adapter.run((EvalCase(case_id="one", input="hello"),), RuntimeProfile())


def test_mcr_verifier_rejects_duplicate_keys_and_labels_trust_scope(tmp_path: Path) -> None:
    bundle = write_report_bundle(_minimal_report(), tmp_path)
    verified = verify_report_bundle(tmp_path)
    assert verified.integrity_valid is True
    assert verified.authenticity_verified is False
    assert verified.trust_scope == "self-consistency-only"
    assert verified.trust.integrity_verified is True
    assert verified.trust.producer_authenticated is False
    assert verified.trust.transparency_verified is False
    assert verified.trust.independently_reproduced is False
    assert verified.trust.deployment_authorization == "not-evaluated"

    original = bundle.json_path.read_text("utf-8")
    duplicate = original.replace("{", '{"schema_version":"0.4.0",', 1)
    bundle.json_path.write_text(duplicate, encoding="utf-8")
    with pytest.raises(MCRVerificationError, match="not valid UTF-8 JSON"):
        verify_report_bundle(tmp_path)


def test_strict_verification_rejects_unavailable_linked_content(tmp_path: Path) -> None:
    report = create_report(
        baseline_snapshot_id=f"mcr:sha256:{'4' * 64}",
        candidate_snapshot_id=f"mcr:sha256:{'5' * 64}",
        release_plan_id=f"mcr:sha256:{'6' * 64}",
        metrics=(),
        decision=MCRDecision(status=MCRStatus.PASS, allowed=True),
    )
    write_report_bundle(report, tmp_path)
    assert verify_report_bundle(tmp_path).bundle_verification_complete is False
    with pytest.raises(MCRVerificationError, match="strict verification"):
        verify_report_bundle(tmp_path, require_complete=True)


def test_report_writer_rejects_symlink_destination_and_target(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    linked_destination = tmp_path / "linked-destination"
    try:
        linked_destination.symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("creating symlinks is not supported in this environment")
    with pytest.raises(ValueError, match="regular local directory"):
        write_report_bundle(_minimal_report(), linked_destination)

    destination = tmp_path / "bundle"
    destination.mkdir()
    outside_file = outside / "outside.json"
    outside_file.write_text("untouched", encoding="utf-8")
    (destination / "mcr-report.json").symlink_to(outside_file)
    with pytest.raises(ValueError, match="regular file"):
        write_report_bundle(_minimal_report(), destination)
    assert outside_file.read_text("utf-8") == "untouched"


def test_verified_file_read_rejects_post_inspection_content_change(tmp_path: Path) -> None:
    artifact = tmp_path / "model.bin"
    artifact.write_bytes(b"current")
    with pytest.raises(ValueError, match="changed after inspection"):
        read_verified_file(
            artifact,
            max_bytes=1024,
            expected_digest=fingerprint("other", namespace="not-the-file-digest"),
        )
