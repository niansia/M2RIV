from __future__ import annotations

import json
from collections.abc import Callable, Iterator

import httpx
import pytest

from m2riv.adapters import ModelAdapter, OpenAICompatibleAdapter, OpenAICompatibleError
from m2riv.core.models import EvalCase, EvidenceAccess, ModelFamily, RuntimeProfile


def _success(content: str = "answer") -> dict[str, object]:
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    }


def _adapter(
    handler: Callable[[httpx.Request], httpx.Response],
    **kwargs: object,
) -> OpenAICompatibleAdapter:
    return OpenAICompatibleAdapter(
        "https://models.example.test/v1",
        "release-candidate",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def test_snapshot_and_cache_identity_are_content_addressed_and_secret_free() -> None:
    first = OpenAICompatibleAdapter(
        "https://models.example.test/v1/",
        "release-candidate",
        api_key="super-secret-key",
        request_profile={"temperature": 0.1, "max_tokens": 32},
        credential_scope="tenant-a",
        deployment_revision="deploy-42",
    )
    same_public_config = OpenAICompatibleAdapter(
        "https://models.example.test/v1",
        "release-candidate",
        api_key="different-secret-key",
        request_profile={"max_tokens": 32, "temperature": 0.1},
        credential_scope="tenant-a",
        deployment_revision="deploy-42",
    )
    changed_profile = OpenAICompatibleAdapter(
        "https://models.example.test/v1",
        "release-candidate",
        request_profile={"temperature": 0.2, "max_tokens": 32},
        credential_scope="tenant-a",
        deployment_revision="deploy-42",
    )

    snapshot = first.describe()
    encoded = snapshot.model_dump_json()
    assert snapshot.id == same_public_config.describe().id
    assert first.adapter_fingerprint == same_public_config.adapter_fingerprint
    assert snapshot.id != changed_profile.describe().id
    assert first.adapter_fingerprint != changed_profile.adapter_fingerprint
    assert "super-secret-key" not in encoded
    assert "different-secret-key" not in encoded
    assert snapshot.model_family == ModelFamily.LLM
    assert snapshot.evidence_access == EvidenceAccess.OUTPUTS
    assert snapshot.labels["identity_scope"] == "declared-remote-config"
    assert snapshot.labels["source_mutability"] == "provider-managed"
    assert snapshot.labels["credential_scope"] == "tenant-a"
    assert snapshot.labels["cache_scope"] == "revision-bound"
    assert snapshot.source.revision == "deploy-42"
    assert snapshot.runtime_profile.parameters == {"temperature": 0.1, "max_tokens": 32}
    assert first.capabilities() == frozenset()
    assert isinstance(first, ModelAdapter)


def test_execution_evidence_settings_participate_in_identity() -> None:
    default = OpenAICompatibleAdapter("https://models.example.test/v1", "model")
    changed_timeout = OpenAICompatibleAdapter(
        "https://models.example.test/v1", "model", timeout_s=10
    )
    changed_retries = OpenAICompatibleAdapter(
        "https://models.example.test/v1", "model", max_retries=2
    )
    changed_response_cap = OpenAICompatibleAdapter(
        "https://models.example.test/v1", "model", max_response_bytes=1024
    )
    changed_elapsed_cap = OpenAICompatibleAdapter(
        "https://models.example.test/v1", "model", max_elapsed_s=60
    )

    assert default.describe().id != changed_timeout.describe().id
    assert default.adapter_fingerprint != changed_timeout.adapter_fingerprint
    assert default.describe().id != changed_retries.describe().id
    assert default.adapter_fingerprint != changed_retries.adapter_fingerprint
    assert default.describe().id != changed_response_cap.describe().id
    assert default.adapter_fingerprint != changed_response_cap.adapter_fingerprint
    assert default.describe().id != changed_elapsed_cap.describe().id
    assert default.adapter_fingerprint != changed_elapsed_cap.adapter_fingerprint


def test_credential_scope_and_deployment_revision_partition_remote_identity() -> None:
    tenant_a_rev_1 = OpenAICompatibleAdapter(
        "https://models.example.test/v1",
        "model",
        api_key="first-secret-key",
        credential_scope="tenant-a",
        deployment_revision="deploy-1",
    )
    tenant_b_rev_1 = OpenAICompatibleAdapter(
        "https://models.example.test/v1",
        "model",
        api_key="second-secret-key",
        credential_scope="tenant-b",
        deployment_revision="deploy-1",
    )
    tenant_a_rev_2 = OpenAICompatibleAdapter(
        "https://models.example.test/v1",
        "model",
        api_key="rotated-secret-key",
        credential_scope="tenant-a",
        deployment_revision="deploy-2",
    )
    tenant_a_rotated_key = OpenAICompatibleAdapter(
        "https://models.example.test/v1",
        "model",
        api_key="rotated-secret-key",
        credential_scope="tenant-a",
        deployment_revision="deploy-1",
    )

    assert tenant_a_rev_1.describe().id != tenant_b_rev_1.describe().id
    assert tenant_a_rev_1.adapter_fingerprint != tenant_b_rev_1.adapter_fingerprint
    assert tenant_a_rev_1.describe().id != tenant_a_rev_2.describe().id
    assert tenant_a_rev_1.adapter_fingerprint != tenant_a_rev_2.adapter_fingerprint
    assert tenant_a_rev_1.describe().id == tenant_a_rotated_key.describe().id
    assert tenant_a_rev_1.adapter_fingerprint == tenant_a_rotated_key.adapter_fingerprint
    encoded = tenant_a_rev_1.describe().model_dump_json()
    assert "first-secret-key" not in encoded
    assert "second-secret-key" not in encoded
    assert "rotated-secret-key" not in encoded


def test_unrevisioned_remote_snapshot_requires_ephemeral_cache() -> None:
    snapshot = OpenAICompatibleAdapter(
        "https://models.example.test/v1",
        "model",
        credential_scope="tenant-a",
    ).describe()

    assert snapshot.source.revision is None
    assert snapshot.labels["cache_scope"] == "ephemeral-required"


def test_string_and_messages_inputs_post_chat_completions() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_success(f"answer-{len(requests)}"))

    adapter = _adapter(
        handler,
        api_key="secret-token",
        request_profile={"temperature": 0.25},
    )
    observations = adapter.run(
        (
            EvalCase(case_id="plain", input="hello"),
            EvalCase(
                case_id="messages",
                input=[
                    {"role": "system", "content": "be concise"},
                    {"role": "user", "content": "hello"},
                ],
            ),
        ),
        RuntimeProfile(seed=7, parameters={"max_tokens": 20}),
    )

    assert [observation.output for observation in observations] == ["answer-1", "answer-2"]
    assert [request.url.path for request in requests] == [
        "/v1/chat/completions",
        "/v1/chat/completions",
    ]
    first_body = json.loads(requests[0].content)
    second_body = json.loads(requests[1].content)
    assert first_body == {
        "temperature": 0.25,
        "max_tokens": 20,
        "model": "release-candidate",
        "messages": [{"role": "user", "content": "hello"}],
    }
    assert second_body["messages"] == [
        {"role": "system", "content": "be concise"},
        {"role": "user", "content": "hello"},
    ]
    assert requests[0].headers["Authorization"] == "Bearer secret-token"
    assert requests[0].headers["Accept-Encoding"] == "identity"
    assert observations[0].snapshot_id == adapter.describe().id
    assert observations[0].seed == 7
    assert observations[0].attempt == 0
    assert observations[0].latency_ms is not None
    assert observations[0].traces["attempts"] == 1
    assert observations[0].traces["usage"] == {
        "prompt_tokens": 3,
        "completion_tokens": 2,
        "total_tokens": 5,
    }
    assert observations[0].traces["latency_ms"] == observations[0].latency_ms
    assert len(observations[0].traces["attempt_latencies_ms"]) == 1
    assert "secret-token" not in observations[0].model_dump_json()


def test_bounded_retry_for_rate_limit_and_server_error() -> None:
    status_codes = [429, 503, 200]
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        status = status_codes[len(seen)]
        seen.append(status)
        if status == 200:
            return httpx.Response(status, json=_success())
        return httpx.Response(status, headers={"Retry-After": "0"})

    observation = _adapter(handler, max_retries=2).run(
        (EvalCase(case_id="retry", input="hello"),), RuntimeProfile()
    )[0]

    assert seen == status_codes
    assert observation.attempt == 2
    assert observation.traces["attempts"] == 3
    assert len(observation.traces["attempt_latencies_ms"]) == 3


def test_retry_after_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "3600"})
        return httpx.Response(200, json=_success())

    monkeypatch.setattr("m2riv.adapters.openai_compatible.time.sleep", sleeps.append)
    _adapter(handler, max_retries=1, retry_after_cap_s=0.25).run(
        (EvalCase(case_id="retry", input="hello"),), RuntimeProfile()
    )

    assert sleeps == [0.25]


def test_non_retryable_client_error_is_attempted_once() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(422, json={"error": "invalid request"})

    with pytest.raises(OpenAICompatibleError, match="HTTP 422"):
        _adapter(handler, max_retries=5).run(
            (EvalCase(case_id="bad", input="hello"),), RuntimeProfile()
        )
    assert calls == 1


def test_transport_error_is_retried_and_sanitized() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("Authorization: Bearer should-not-escape", request=request)

    with pytest.raises(OpenAICompatibleError) as captured:
        _adapter(handler, api_key="actual-secret", max_retries=1).run(
            (EvalCase(case_id="transport", input="hello"),), RuntimeProfile()
        )

    assert attempts == 2
    assert "Authorization" not in str(captured.value)
    assert "actual-secret" not in str(captured.value)
    assert "should-not-escape" not in str(captured.value)
    assert "after 2 attempts" in str(captured.value)


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(400, json={"error": "Authorization: Bearer leaked-secret"}), "HTTP 400"),
        (httpx.Response(200, content=b"not-json"), "invalid JSON"),
        (httpx.Response(200, json={"choices": []}), "no valid choice"),
        (
            httpx.Response(200, json={"choices": [{"message": {"content": None}}]}),
            "missing text content",
        ),
        (
            httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}], "usage": []}),
            "invalid usage",
        ),
    ],
)
def test_api_and_response_errors_fail_closed_without_leaking_body(
    response: httpx.Response,
    expected: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return response

    with pytest.raises(OpenAICompatibleError) as captured:
        _adapter(handler, api_key="leaked-secret", max_retries=0).run(
            (EvalCase(case_id="bad", input="hello"),), RuntimeProfile()
        )

    assert expected in str(captured.value)
    assert "leaked-secret" not in str(captured.value)
    assert "Authorization" not in str(captured.value)


def test_non_finite_usage_fails_closed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b'{"choices":[{"message":{"content":"ok"}}],"usage":{"tokens":NaN}}',
            headers={"Content-Type": "application/json"},
        )

    with pytest.raises(OpenAICompatibleError, match="invalid usage"):
        _adapter(handler).run((EvalCase(case_id="bad", input="hello"),), RuntimeProfile())


@pytest.mark.parametrize(
    "response_payload",
    [
        _success("the endpoint echoed api-secret-canary"),
        {
            "choices": [{"message": {"content": "ordinary output"}}],
            "usage": {"provider_note": "Bearer api-secret-canary"},
        },
        {
            "choices": [{"message": {"content": "ordinary output"}}],
            "usage": {"api-secret-canary": 1},
        },
    ],
)
def test_response_secret_canary_fails_before_observation(
    response_payload: dict[str, object],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_payload)

    with pytest.raises(OpenAICompatibleError) as captured:
        _adapter(handler, api_key="api-secret-canary").run(
            (EvalCase(case_id="echo", input="hello"),), RuntimeProfile()
        )

    message = str(captured.value)
    assert "secret-safety validation" in message
    assert "api-secret-canary" not in message
    assert "Bearer" not in message


def test_secret_or_hostile_case_id_never_enters_error() -> None:
    called = False
    hostile_case_id = "api-secret-canary\r\n\x1b[31mAuthorization: Bearer api-secret-canary"

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(401)

    with pytest.raises(OpenAICompatibleError) as captured:
        _adapter(handler, api_key="api-secret-canary").run(
            (EvalCase(case_id=hostile_case_id, input="hello"),), RuntimeProfile()
        )

    message = str(captured.value)
    assert not called
    assert "api-secret-canary" not in message
    assert "Authorization" not in message
    assert "\r" not in message and "\n" not in message and "\x1b" not in message
    assert "case #1" in message


@pytest.mark.parametrize(
    "constructor_kwargs",
    [
        {"endpoint": "https://models.example.test/api-secret-canary/v1"},
        {"model": "model-api-secret-canary"},
        {"request_profile": {"metadata": "api-secret-canary"}},
        {"request_profile": {"api-secret-canary": "ordinary"}},
        {"credential_scope": "api-secret-canary"},
        {"deployment_revision": "api-secret-canary"},
    ],
)
def test_secret_cannot_enter_public_adapter_configuration(
    constructor_kwargs: dict[str, object],
) -> None:
    endpoint = str(constructor_kwargs.pop("endpoint", "https://models.example.test/v1"))
    model = str(constructor_kwargs.pop("model", "model"))
    with pytest.raises(ValueError) as captured:
        OpenAICompatibleAdapter(
            endpoint,
            model,
            api_key="api-secret-canary",
            **constructor_kwargs,
        )
    assert "api-secret-canary" not in str(captured.value)


def test_secret_cannot_enter_runtime_parameters_or_prompt() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json=_success())

    adapter = _adapter(handler, api_key="api-secret-canary")
    with pytest.raises(OpenAICompatibleError) as runtime_error:
        adapter.run(
            (EvalCase(case_id="runtime", input="hello"),),
            RuntimeProfile(parameters={"metadata": "api-secret-canary"}),
        )
    with pytest.raises(OpenAICompatibleError) as prompt_error:
        adapter.run((EvalCase(case_id="prompt", input="echo api-secret-canary"),), RuntimeProfile())
    assert not called
    assert "api-secret-canary" not in str(runtime_error.value)
    assert "api-secret-canary" not in str(prompt_error.value)


def test_oversized_response_is_stopped_during_streaming() -> None:
    yielded: list[int] = []

    class ChunkStream(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            for index, chunk in enumerate((b"1234567890", b"abcdefghij", b"not-consumed")):
                yielded.append(index)
                yield chunk

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=ChunkStream())

    with pytest.raises(OpenAICompatibleError, match="evidence size limit"):
        _adapter(handler, max_response_bytes=16).run(
            (EvalCase(case_id="large", input="hello"),), RuntimeProfile()
        )
    assert yielded == [0, 1]


def test_slow_drip_response_is_stopped_by_cumulative_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]

    class SlowStream(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            clock[0] = 0.6
            yield b"{"
            clock[0] = 1.2
            yield b'"never":"consumed"}'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=SlowStream())

    monkeypatch.setattr("m2riv.adapters.openai_compatible.time.perf_counter", lambda: clock[0])
    with pytest.raises(OpenAICompatibleError, match="cumulative elapsed-time limit"):
        _adapter(handler, max_elapsed_s=0.5).run(
            (EvalCase(case_id="slow", input="hello"),), RuntimeProfile()
        )


@pytest.mark.parametrize(
    "input_value",
    [[], {"role": "user", "content": "not-an-array"}, [{"role": "user"}], ["hello"]],
)
def test_invalid_case_inputs_make_no_request(input_value: object) -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json=_success())

    with pytest.raises(OpenAICompatibleError):
        _adapter(handler).run((EvalCase(case_id="invalid", input=input_value),), RuntimeProfile())
    assert not called


@pytest.mark.parametrize(
    "kwargs",
    [
        {"endpoint": "https://user:secret@models.example.test/v1"},
        {"endpoint": "https://models.example.test/v1?api_key=secret"},
        {"request_profile": {"Authorization": "Bearer secret"}},
        {"request_profile": {"metadata": {"api_key": "secret"}}},
        {"request_profile": {"tools": []}},
        {"timeout_s": float("nan")},
        {"timeout_s": 301},
        {"max_retries": True},
        {"max_retries": 6},
        {"retry_after_cap_s": float("inf")},
        {"retry_after_cap_s": 61},
        {"max_response_bytes": 0},
        {"max_response_bytes": 100 * 1024 * 1024 + 1},
        {"max_elapsed_s": float("nan")},
        {"max_elapsed_s": 0},
        {"max_elapsed_s": 3601},
        {"credential_scope": ""},
        {"credential_scope": "tenant name"},
        {"credential_scope": "tenant\nname"},
        {"deployment_revision": "release#1"},
    ],
)
def test_unsafe_or_invalid_configuration_is_rejected(kwargs: dict[str, object]) -> None:
    endpoint = str(kwargs.pop("endpoint", "https://models.example.test/v1"))
    with pytest.raises(ValueError):
        OpenAICompatibleAdapter(endpoint, "model", **kwargs)


def test_runtime_profile_cannot_smuggle_headers_or_owned_fields() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json=_success())

    adapter = _adapter(handler)
    with pytest.raises(ValueError, match="credentials or headers"):
        adapter.run(
            (EvalCase(case_id="bad", input="hello"),),
            RuntimeProfile(parameters={"headers": {"Authorization": "secret"}}),
        )
    with pytest.raises(ValueError, match="adapter-owned field"):
        adapter.run(
            (EvalCase(case_id="bad", input="hello"),),
            RuntimeProfile(parameters={"model": "unexpected"}),
        )
    assert not called


def test_injected_client_is_supported_and_not_closed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_success())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        adapter = OpenAICompatibleAdapter(
            "https://models.example.test/v1/chat/completions",
            "model",
            client=client,
        )
        assert adapter.run((EvalCase(case_id="one", input="hello"),), RuntimeProfile())[0].output
        assert not client.is_closed
    finally:
        client.close()
