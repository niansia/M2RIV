from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from xml.etree import ElementTree

import httpx
import pytest
from typer.testing import CliRunner

import m2riv.engine.cache as cache_module
from m2riv.adapters import OpenAICompatibleAdapter, OpenAICompatibleError
from m2riv.adapters.recorded import RecordedAdapter
from m2riv.bisect import (
    BisectConfidence,
    BisectMode,
    BisectOutcome,
    BisectStatus,
    bisect_regression,
)
from m2riv.cli import _write_github_summary, app
from m2riv.core.identity import build_local_snapshot, fingerprint, observation_content_id
from m2riv.core.models import EvalCase, ModelFamily, Observation, RuntimeProfile
from m2riv.engine import CacheKey, ObservationCache, PairedRunner
from m2riv.engine.cache import MAX_CACHE_ENTRY_BYTES
from m2riv.io import InputFormatError, load_policy, load_suite
from m2riv.io.loaders import (
    MAX_JSON_DEPTH,
    MAX_JSONL_LINE_BYTES,
    MAX_JSONL_RECORDS,
    MAX_POLICY_BYTES,
    MAX_YAML_ALIASES,
)
from m2riv.pipeline import ReleaseComparison
from m2riv.reports.ci import render_junit, render_sarif
from m2riv.reports.models import (
    MCRDecision,
    MCRFinding,
    MCRStatus,
    create_report,
)

runner = CliRunner()


def _content_id(label: str) -> str:
    return f"m2riv:sha256:{fingerprint(label, namespace='stage4-adversarial')}"


def _hostile_report(message: str, *, rule_id: str = "hostile-rule"):
    finding = MCRFinding(
        rule_id=rule_id,
        metric_id="accuracy",
        status=MCRStatus.BLOCK,
        message=message,
    )
    return create_report(
        baseline_snapshot_id=_content_id("baseline"),
        candidate_snapshot_id=_content_id("candidate"),
        metrics=(),
        decision=MCRDecision(
            status=MCRStatus.BLOCK,
            allowed=False,
            findings=(finding,),
        ),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _cache_fixture() -> tuple[CacheKey, Observation]:
    snapshot_id = _content_id("cache-snapshot")
    case = EvalCase(case_id="cache-case", input="hello")
    profile = RuntimeProfile()
    output = "safe output"
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
    return (
        CacheKey.for_case(
            snapshot_id=snapshot_id,
            case=case,
            runtime_profile=profile,
            adapter_fingerprint="stage4-adversarial@1",
        ),
        observation,
    )


def _write_cli_gate_inputs(root: Path) -> tuple[Path, Path]:
    suite = root / "suite.jsonl"
    policy = root / "policy.yaml"
    suite.write_text(
        '{"case_id":"case-1","input":"hello","expected":"ok"}\n',
        encoding="utf-8",
    )
    policy.write_text(
        "schema_version: 1.0.0\n"
        "policy_id: api-cli\n"
        "rules:\n"
        "  - rule_id: quality\n"
        "    metric: accuracy\n"
        "    margin: 0.1\n"
        "    min_pairs: 1\n",
        encoding="utf-8",
    )
    return suite, policy


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_jsonl_non_finite_constants_are_rejected(tmp_path: Path, constant: str) -> None:
    suite = tmp_path / "suite.jsonl"
    suite.write_text(
        f'{{"case_id":"poison","input":{{"value":{constant}}}}}\n',
        encoding="utf-8",
    )

    with pytest.raises(InputFormatError, match=r"NaN|Infinity|invalid JSON"):
        load_suite(suite)


def test_recorded_jsonl_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    recorded = tmp_path / "recorded.jsonl"
    recorded.write_text(
        '{"case_id":"same","output":"first"}\n{"case_id":"same","output":"second"}\n',
        encoding="utf-8",
    )
    snapshot = build_local_snapshot(recorded, model_family=ModelFamily.CUSTOM)

    with pytest.raises(InputFormatError, match="duplicate case_id"):
        RecordedAdapter.from_jsonl(recorded, snapshot)


def test_jsonl_duplicate_object_keys_are_rejected(tmp_path: Path) -> None:
    suite = tmp_path / "duplicate-keys.jsonl"
    suite.write_text(
        '{"case_id":"trusted","case_id":"shadowed","input":"hello"}\n',
        encoding="utf-8",
    )

    with pytest.raises(InputFormatError, match=r"duplicate.*key|key.*duplicate"):
        load_suite(suite)


def test_jsonl_huge_single_line_is_rejected_before_materialization(tmp_path: Path) -> None:
    suite = tmp_path / "huge-suite.jsonl"
    suite.write_text(
        json.dumps({"case_id": "huge", "input": "x" * MAX_JSONL_LINE_BYTES}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(InputFormatError, match=r"large|limit|size|bytes|line"):
        load_suite(suite)


def test_deeply_nested_jsonl_is_a_sanitized_format_error(tmp_path: Path) -> None:
    suite = tmp_path / "deep-suite.jsonl"
    depth = MAX_JSON_DEPTH + 1
    suite.write_text(
        '{"case_id":"deep","input":' + "[" * depth + "0" + "]" * depth + "}\n",
        encoding="utf-8",
    )

    with pytest.raises(InputFormatError, match=r"depth|nested|invalid JSON|limit"):
        load_suite(suite)


def test_policy_yaml_alias_amplification_is_rejected(tmp_path: Path) -> None:
    policy = tmp_path / "aliases.yaml"
    aliases = "\n".join("  - *rule" for _ in range(MAX_YAML_ALIASES + 1))
    policy.write_text(
        "schema_version: 1.0.0\n"
        "policy_id: alias-bomb\n"
        "rules:\n"
        "  - &rule\n"
        "    rule_id: repeated\n"
        "    metric: accuracy\n"
        "    margin: 0.1\n"
        f"{aliases}\n",
        encoding="utf-8",
    )

    with pytest.raises(InputFormatError, match=r"alias|limit"):
        load_policy(policy)


def test_policy_yaml_duplicate_keys_are_rejected(tmp_path: Path) -> None:
    policy = tmp_path / "duplicate-keys.yaml"
    policy.write_text(
        "schema_version: 1.0.0\n"
        "policy_id: trusted\n"
        "policy_id: shadowed\n"
        "rules:\n"
        "  - rule_id: quality\n"
        "    metric: accuracy\n"
        "    margin: 0.1\n",
        encoding="utf-8",
    )

    with pytest.raises(InputFormatError, match=r"duplicate.*key|key.*duplicate"):
        load_policy(policy)


def test_policy_yaml_recursive_alias_is_rejected(tmp_path: Path) -> None:
    policy = tmp_path / "recursive-alias.yaml"
    policy.write_text(
        "schema_version: 1.0.0\n"
        "policy_id: recursive\n"
        "rules:\n"
        "  - &rule\n"
        "    rule_id: quality\n"
        "    metric: accuracy\n"
        "    margin: 0.1\n"
        "    recursive: *rule\n",
        encoding="utf-8",
    )

    with pytest.raises(InputFormatError, match=r"recursive|cycle|alias|depth"):
        load_policy(policy)


def test_oversized_policy_is_rejected_before_yaml_construction(tmp_path: Path) -> None:
    policy = tmp_path / "oversized.yaml"
    policy.write_text(
        "schema_version: 1.0.0\n"
        "policy_id: oversized\n"
        "rules:\n"
        "  - rule_id: quality\n"
        "    metric: accuracy\n"
        "    margin: 0.1\n"
        f"padding: {'x' * MAX_POLICY_BYTES}\n",
        encoding="utf-8",
    )

    with pytest.raises(InputFormatError, match=r"large|limit|size|bytes"):
        load_policy(policy)


def test_jsonl_record_count_is_bounded(tmp_path: Path) -> None:
    suite = tmp_path / "too-many-records.jsonl"
    row = '{"case_id":"same","input":null}\n'
    # The parser's resource budget is enforced before semantic duplicate-ID
    # validation, so a compact repeated row keeps this adversarial test cheap.
    suite.write_text(row * (MAX_JSONL_RECORDS + 1), encoding="utf-8")

    with pytest.raises(InputFormatError, match=r"record.*limit|count.*exceed"):
        load_suite(suite)


def test_junit_metacharacters_remain_data_not_xml_structure() -> None:
    payload = '<failure message="forged">&\n]]><script>alert(1)</script>'
    rule_id = 'rule"><testcase name="forged'
    rendered = render_junit(_hostile_report(payload, rule_id=rule_id))
    root = ElementTree.fromstring(rendered)

    cases = root.findall("testcase")
    assert len(cases) == 1
    assert cases[0].attrib["name"] == rule_id
    failure = cases[0].find("failure")
    assert failure is not None
    assert failure.attrib["message"] == payload
    assert failure.text == payload
    assert root.findall(".//script") == []


def test_sarif_metacharacters_remain_json_data() -> None:
    payload = '"}, {"ruleId":"forged","message":{"text":"secret"}}\n\u001b[31m'
    rule_id = 'rule"},{"id":"forged'
    document = json.loads(render_sarif(_hostile_report(payload, rule_id=rule_id)))
    driver = document["runs"][0]["tool"]["driver"]
    results = document["runs"][0]["results"]

    assert len(driver["rules"]) == 1
    assert len(results) == 1
    assert driver["rules"][0]["id"] == rule_id
    assert results[0]["message"]["text"] == payload


def test_github_summary_write_error_does_not_echo_sensitive_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "ghp_stage4_canary_DO_NOT_LOG"
    invalid_summary = tmp_path / secret / "missing-parent" / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(invalid_summary))

    # Only the report attribute is accessed by the summary writer.
    comparison = cast(
        ReleaseComparison,
        SimpleNamespace(report=_hostile_report("ordinary finding")),
    )
    _write_github_summary(comparison)

    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err


@pytest.mark.parametrize(
    "endpoint",
    [
        "file:///etc/passwd",
        "data:text/plain,hello",
        "ftp://example.test/v1",
        "//example.test/v1",
        "https://user:password@example.test/v1",
        "https://example.test/v1?api_key=secret",
        "https://example.test/v1#fragment",
    ],
)
def test_openai_adapter_rejects_ambiguous_or_credentialed_urls(endpoint: str) -> None:
    with pytest.raises(ValueError, match=r"HTTP|credentials|query|fragment"):
        OpenAICompatibleAdapter(endpoint, "model")


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_openai_adapter_rejects_non_finite_network_budgets(bad_value: float) -> None:
    with pytest.raises(ValueError):
        OpenAICompatibleAdapter("https://example.test/v1", "model", timeout_s=bad_value)
    with pytest.raises(ValueError):
        OpenAICompatibleAdapter(
            "https://example.test/v1",
            "model",
            retry_after_cap_s=bad_value,
        )


def test_api_key_is_absent_from_snapshot_fingerprint_repr_and_cache(tmp_path: Path) -> None:
    secret = "sk-stage4-canary-never-persist"

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {secret}"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "safe output"}}],
                "usage": {"total_tokens": 4},
            },
        )

    adapter = OpenAICompatibleAdapter(
        "https://example.test/v1",
        "model",
        api_key=secret,
        transport=httpx.MockTransport(respond),
    )
    case = EvalCase(case_id="case-1", input="hello", expected="safe output")
    profile = RuntimeProfile()
    observation = adapter.run((case,), profile)[0]
    snapshot = adapter.describe()
    cache = ObservationCache(tmp_path / "cache")
    key = CacheKey.for_case(
        snapshot_id=snapshot.id,
        case=case,
        runtime_profile=profile,
        adapter_fingerprint=adapter.adapter_fingerprint,
    )
    cache.put(key, observation)

    persisted = b"".join(path.read_bytes() for path in (tmp_path / "cache").rglob("*.json"))
    surfaces = "\n".join(
        (
            snapshot.model_dump_json(),
            adapter.adapter_fingerprint,
            repr(adapter),
            persisted.decode("utf-8"),
        )
    )
    assert secret not in surfaces
    assert f"Bearer {secret}" not in surfaces


@pytest.mark.parametrize("field", ["content", "usage"])
def test_endpoint_cannot_echo_api_key_into_observation(
    field: str,
) -> None:
    secret = "sk-stage4-malicious-echo"

    def respond(_request: httpx.Request) -> httpx.Response:
        content = secret if field == "content" else "safe output"
        usage = {"provider_debug": f"Authorization: Bearer {secret}"} if field == "usage" else {}
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}], "usage": usage},
        )

    adapter = OpenAICompatibleAdapter(
        "https://example.test/v1",
        "model",
        api_key=secret,
        transport=httpx.MockTransport(respond),
    )

    with pytest.raises(OpenAICompatibleError) as captured:
        adapter.run((EvalCase(case_id="case-1", input="hello"),), RuntimeProfile())
    assert secret not in str(captured.value)
    assert f"Bearer {secret}" not in str(captured.value)


def test_api_key_in_untrusted_case_id_is_redacted_from_errors() -> None:
    secret = "sk-stage4-case-id-canary"
    adapter = OpenAICompatibleAdapter(
        "https://example.test/v1",
        "model",
        api_key=secret,
        transport=httpx.MockTransport(lambda _request: httpx.Response(401)),
    )

    with pytest.raises(OpenAICompatibleError) as captured:
        adapter.run((EvalCase(case_id=secret, input="hello"),), RuntimeProfile())
    assert secret not in str(captured.value)
    assert "Authorization" not in str(captured.value)


def test_retry_after_is_capped_and_does_not_expand_attempt_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_count = 0
    sleeps: list[float] = []

    def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if request_count < 3:
            return httpx.Response(429, headers={"Retry-After": "999999999"})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
        )

    monkeypatch.setattr("m2riv.adapters.openai_compatible.time.sleep", sleeps.append)
    adapter = OpenAICompatibleAdapter(
        "https://example.test/v1",
        "model",
        max_retries=2,
        retry_after_cap_s=0.01,
        transport=httpx.MockTransport(respond),
    )
    observation = adapter.run((EvalCase(case_id="case-1", input="hello"),), RuntimeProfile())[0]

    assert request_count == 3
    assert sleeps == [0.01, 0.01]
    assert observation.attempt == 2
    assert observation.traces["attempts"] == 3


def test_bisect_callback_exception_is_fail_closed_and_secret_free() -> None:
    secret = "Authorization: Bearer sk-stage4-bisect-canary"

    def evaluate(index: int) -> BisectStatus:
        if index == 7:
            raise RuntimeError(f"provider request failed; {secret}")
        return BisectStatus.PASS

    result = bisect_regression(8, evaluate)

    assert result.outcome is BisectOutcome.INCONCLUSIVE
    assert result.confidence is BisectConfidence.NONE
    assert any(record.status is BisectStatus.ERROR for record in result.evaluations)
    assert secret not in repr(result)


def test_bisect_observed_non_monotonicity_never_reports_false_onset() -> None:
    statuses = [
        BisectStatus.BLOCK,
        BisectStatus.BLOCK,
        BisectStatus.PASS,
        BisectStatus.PASS,
    ]
    result = bisect_regression(
        len(statuses),
        lambda index: statuses[index],
        mode=BisectMode.LINEAR_AUDIT,
    )

    assert result.outcome is BisectOutcome.NON_MONOTONIC
    assert result.first_failing_index is None
    assert result.confirmed_interval is None


def test_monotonic_bisect_endpoint_contradiction_has_no_confidence_or_onset() -> None:
    statuses = [BisectStatus.BLOCK, BisectStatus.BLOCK, BisectStatus.PASS]
    result = bisect_regression(
        len(statuses),
        lambda index: statuses[index],
    )

    assert result.outcome is BisectOutcome.NON_MONOTONIC
    assert result.first_failing_index is None
    assert result.confidence is BisectConfidence.NONE


def test_oversized_cache_entry_is_a_miss_without_opening_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key, _observation = _cache_fixture()
    cache = ObservationCache(tmp_path / "cache")
    path = cache.path_for(key)
    path.parent.mkdir(parents=True)
    with path.open("wb") as stream:
        stream.truncate(MAX_CACHE_ENTRY_BYTES + 1)

    opened = False
    real_open = cache_module.os.open

    def tracked_open(*args: object, **kwargs: object) -> int:
        nonlocal opened
        opened = True
        return real_open(*args, **kwargs)

    monkeypatch.setattr(cache_module.os, "open", tracked_open)
    assert cache.get(key) is None
    assert opened is False


def test_cache_put_rejects_envelope_over_size_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key, observation = _cache_fixture()
    cache = ObservationCache(tmp_path / "cache")
    monkeypatch.setattr(
        cache_module,
        "canonical_json",
        lambda _value: b"x" * (MAX_CACHE_ENTRY_BYTES + 1),
    )

    with pytest.raises(ValueError, match=r"cache.*exceed|byte.*limit"):
        cache.put(key, observation)
    assert not cache.path_for(key).exists()


def test_cache_entry_symlink_is_never_read_or_overwritten(tmp_path: Path) -> None:
    key, observation = _cache_fixture()
    cache = ObservationCache(tmp_path / "cache")
    path = cache.path_for(key)
    path.parent.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text("do not touch", encoding="utf-8")
    try:
        path.symlink_to(outside)
    except (NotImplementedError, OSError):
        pytest.skip("creating file symlinks is not supported in this environment")

    assert cache.get(key) is None
    with pytest.raises(ValueError, match=r"regular|symlink|reparse"):
        cache.put(key, observation)
    assert outside.read_text("utf-8") == "do not touch"


def test_cache_shard_symlink_cannot_redirect_write_outside_root(tmp_path: Path) -> None:
    key, observation = _cache_fixture()
    cache = ObservationCache(tmp_path / "cache")
    path = cache.path_for(key)
    cache.root.mkdir()
    outside = tmp_path / "outside-shard"
    outside.mkdir()
    try:
        path.parent.symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("creating directory symlinks is not supported in this environment")

    with pytest.raises(ValueError, match=r"regular|symlink|reparse"):
        cache.put(key, observation)
    assert list(outside.iterdir()) == []


def test_cache_root_symlink_cannot_redirect_write(tmp_path: Path) -> None:
    key, observation = _cache_fixture()
    outside = tmp_path / "outside-root"
    outside.mkdir()
    cache_root = tmp_path / "cache-link"
    try:
        cache_root.symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("creating directory symlinks is not supported in this environment")
    cache = ObservationCache(cache_root)

    with pytest.raises(ValueError, match=r"root|regular|symlink|reparse"):
        cache.put(key, observation)
    assert list(outside.rglob("*.json")) == []


def test_compare_api_cli_never_echoes_environment_api_keys(tmp_path: Path) -> None:
    suite, policy = _write_cli_gate_inputs(tmp_path)
    baseline_secret = "sk-stage4-cli-baseline-canary"
    candidate_secret = "sk-stage4-cli-candidate-canary"
    result = runner.invoke(
        app,
        [
            "compare-api",
            f"https://user:{baseline_secret}@example.test/v1",
            "https://example.test/v1",
            "--baseline-model",
            "model",
            "--candidate-model",
            candidate_secret,
            "--suite",
            str(suite),
            "--policy",
            str(policy),
            "--output",
            str(tmp_path / "run"),
            "--resamples",
            "100",
        ],
        env={
            "M2RIV_BASELINE_API_KEY": baseline_secret,
            "M2RIV_CANDIDATE_API_KEY": candidate_secret,
        },
    )

    assert result.exit_code == 3
    rendered = result.stdout + result.stderr
    assert baseline_secret not in rendered
    assert candidate_secret not in rendered
    assert baseline_secret not in str(result.exception)
    assert candidate_secret not in str(result.exception)


def test_compare_api_runtime_failure_uses_fail_closed_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suite, policy = _write_cli_gate_inputs(tmp_path)

    def fail_run(
        _adapter: OpenAICompatibleAdapter,
        _cases: object,
        _profile: RuntimeProfile,
    ) -> tuple[Observation, ...]:
        raise OpenAICompatibleError("sanitized provider failure")

    monkeypatch.setattr(OpenAICompatibleAdapter, "run", fail_run)
    result = runner.invoke(
        app,
        [
            "compare-api",
            "https://baseline.example.test/v1",
            "https://candidate.example.test/v1",
            "--baseline-model",
            "baseline",
            "--candidate-model",
            "candidate",
            "--suite",
            str(suite),
            "--policy",
            str(policy),
            "--output",
            str(tmp_path / "run"),
            "--resamples",
            "100",
        ],
    )

    assert result.exit_code == 3
    assert "ERROR: sanitized provider failure" in result.stderr


def test_paired_remote_credentials_cannot_alias_candidate_to_baseline_cache(
    tmp_path: Path,
) -> None:
    baseline_calls = 0
    candidate_calls = 0

    def baseline_response(_request: httpx.Request) -> httpx.Response:
        nonlocal baseline_calls
        baseline_calls += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "baseline-output"}}]},
        )

    def candidate_response(_request: httpx.Request) -> httpx.Response:
        nonlocal candidate_calls
        candidate_calls += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "candidate-output"}}]},
        )

    baseline = OpenAICompatibleAdapter(
        "https://same.example.test/v1",
        "same-model",
        api_key="sk-baseline-scope",
        transport=httpx.MockTransport(baseline_response),
    )
    candidate = OpenAICompatibleAdapter(
        "https://same.example.test/v1",
        "same-model",
        api_key="sk-candidate-scope",
        transport=httpx.MockTransport(candidate_response),
    )
    case = EvalCase(case_id="case-1", input="hello")
    result = PairedRunner(ObservationCache(tmp_path / "cache")).run(
        baseline,
        candidate,
        (case,),
        profile=RuntimeProfile(),
        baseline_adapter_fingerprint=f"baseline:{baseline.adapter_fingerprint}",
        candidate_adapter_fingerprint=f"candidate:{candidate.adapter_fingerprint}",
    )

    assert baseline_calls == 1
    assert candidate_calls == 1
    assert result.cases[0].baseline.output == "baseline-output"
    assert result.cases[0].candidate.output == "candidate-output"
    assert result.cases[0].candidate_cache_hit is False


def test_compare_api_cli_scopes_baseline_and_candidate_cache_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suite, policy = _write_cli_gate_inputs(tmp_path)
    captured: dict[str, object] = {}

    def intercept_compare(**kwargs: object) -> ReleaseComparison:
        captured.update(kwargs)
        raise OpenAICompatibleError("stop after identity capture")

    monkeypatch.setattr("m2riv.cli.compare_exact_match", intercept_compare)
    result = runner.invoke(
        app,
        [
            "compare-api",
            "https://same.example.test/v1",
            "https://same.example.test/v1",
            "--baseline-model",
            "same-model",
            "--candidate-model",
            "same-model",
            "--suite",
            str(suite),
            "--policy",
            str(policy),
            "--output",
            str(tmp_path / "run"),
            "--resamples",
            "100",
        ],
        env={
            "M2RIV_BASELINE_API_KEY": "sk-baseline-scope",
            "M2RIV_CANDIDATE_API_KEY": "sk-candidate-scope",
        },
    )

    assert result.exit_code == 3
    assert captured["baseline_adapter_fingerprint"] != captured["candidate_adapter_fingerprint"]


@pytest.mark.parametrize(
    ("rows", "expected_fragment"),
    [
        (
            [
                {"checkpoint": "duplicate", "status": "pass"},
                {"checkpoint": "duplicate", "status": "block"},
            ],
            "duplicate checkpoint",
        ),
        ([{"checkpoint": "bad\u001b[31m", "status": "pass"}], "safe non-blank"),
        ([{"checkpoint": "one", "status": "unknown"}], "unsupported checkpoint status"),
    ],
)
def test_bisect_manifest_rejects_duplicate_control_and_unknown_values(
    tmp_path: Path,
    rows: list[dict[str, str]],
    expected_fragment: str,
) -> None:
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["bisect", str(manifest)])

    assert result.exit_code == 3
    assert expected_fragment in result.stderr
    assert "\x1b" not in result.stdout + result.stderr


def test_bisect_manifest_oversize_is_fail_closed(tmp_path: Path) -> None:
    manifest = tmp_path / "oversized-manifest.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "checkpoint": "x" * MAX_JSONL_LINE_BYTES,
                "status": "pass",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["bisect", str(manifest)])

    assert result.exit_code == 3
    assert "line exceeds" in result.stderr


@pytest.mark.parametrize("uncertain_status", ["warn", "error"])
def test_bisect_cli_warn_and_error_are_never_success(
    tmp_path: Path,
    uncertain_status: str,
) -> None:
    manifest = tmp_path / f"{uncertain_status}.jsonl"
    manifest.write_text(
        '{"checkpoint":"first","status":"pass"}\n'
        f'{{"checkpoint":"last","status":"{uncertain_status}"}}\n',
        encoding="utf-8",
    )

    result = runner.invoke(app, ["bisect", str(manifest)])

    assert result.exit_code == 3
    document = json.loads(result.stdout)
    assert document["outcome"] == "inconclusive"
    assert document["first_failing_checkpoint"] is None


def test_bisect_cli_non_monotonic_result_is_never_success(tmp_path: Path) -> None:
    manifest = tmp_path / "non-monotonic.jsonl"
    manifest.write_text(
        '{"checkpoint":"first","status":"block"}\n{"checkpoint":"last","status":"pass"}\n',
        encoding="utf-8",
    )

    result = runner.invoke(app, ["bisect", str(manifest)])

    assert result.exit_code == 2
    document = json.loads(result.stdout)
    assert document["outcome"] == "non_monotonic"
    assert document["first_failing_checkpoint"] is None
    assert document["confidence"] == "none"


@pytest.mark.parametrize("uncertain_status", ["warn", "error"])
def test_bisect_manifest_cannot_skip_known_interior_uncertainty(
    tmp_path: Path,
    uncertain_status: str,
) -> None:
    manifest = tmp_path / f"hidden-{uncertain_status}.jsonl"
    statuses = ["pass", uncertain_status, "pass", "pass", "block"]
    manifest.write_text(
        "".join(
            json.dumps({"checkpoint": f"cp-{index}", "status": status}) + "\n"
            for index, status in enumerate(statuses)
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["bisect", str(manifest)])

    assert result.exit_code == 3
    document = json.loads(result.stdout)
    assert document["outcome"] == "inconclusive"
    assert document["first_failing_checkpoint"] is None


def test_bisect_manifest_cannot_skip_known_interior_reversal(tmp_path: Path) -> None:
    manifest = tmp_path / "hidden-reversal.jsonl"
    statuses = ["pass", "block", "pass", "pass", "block"]
    manifest.write_text(
        "".join(
            json.dumps({"checkpoint": f"cp-{index}", "status": status}) + "\n"
            for index, status in enumerate(statuses)
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["bisect", str(manifest)])

    assert result.exit_code == 2
    document = json.loads(result.stdout)
    assert document["outcome"] == "non_monotonic"
    assert document["first_failing_checkpoint"] is None


@pytest.mark.parametrize(
    ("interior_status", "expected_exit", "expected_outcome"),
    [
        ("warn", 3, "inconclusive"),
        ("error", 3, "inconclusive"),
        ("block", 2, "non_monotonic"),
    ],
)
def test_sparse_manifest_cannot_hide_known_interior_evidence(
    tmp_path: Path,
    interior_status: str,
    expected_exit: int,
    expected_outcome: str,
) -> None:
    manifest = tmp_path / f"sparse-hidden-{interior_status}.jsonl"
    statuses = ["pass", interior_status, "pass"]
    manifest.write_text(
        "".join(
            json.dumps({"checkpoint": f"cp-{index}", "status": status}) + "\n"
            for index, status in enumerate(statuses)
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["bisect", str(manifest), "--mode", "sparse_audit", "--sparse-points", "2"],
    )

    assert result.exit_code == expected_exit
    document = json.loads(result.stdout)
    assert document["outcome"] == expected_outcome
    assert document["first_failing_checkpoint"] is None


@pytest.mark.parametrize("uncertain_status", ["warn", "error"])
def test_bisect_uncertainty_dominates_simultaneous_reversal(
    tmp_path: Path,
    uncertain_status: str,
) -> None:
    manifest = tmp_path / f"mixed-{uncertain_status}.jsonl"
    statuses = ["block", uncertain_status, "pass"]
    manifest.write_text(
        "".join(
            json.dumps({"checkpoint": f"cp-{index}", "status": status}) + "\n"
            for index, status in enumerate(statuses)
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["bisect", str(manifest)])

    assert result.exit_code == 3
    document = json.loads(result.stdout)
    assert document["outcome"] == "inconclusive"
    assert document["confidence"] == "none"
    assert document["first_failing_checkpoint"] is None
