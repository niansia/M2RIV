"""Synchronous adapter for OpenAI-compatible chat-completions endpoints."""

from __future__ import annotations

import copy
import ipaddress
import json
import math
import re
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from m2riv.adapters.base import AdapterCapability
from m2riv.core.identity import canonical_json, fingerprint, observation_content_id
from m2riv.core.models import (
    EvalCase,
    EvidenceAccess,
    ModelFamily,
    ModelRef,
    ModelSnapshot,
    Observation,
    RuntimeProfile,
)
from m2riv.io.json import StrictJSONError, parse_strict_json

_ADAPTER_VERSION = "1.0.0"
_DEFAULT_MAX_RESPONSE_BYTES = 10 * 1024 * 1024
_MAX_CONFIGURED_RESPONSE_BYTES = 100 * 1024 * 1024
_MAX_ELAPSED_S = 3600.0
_MAX_RETRIES = 5
_MAX_RETRY_AFTER_CAP_S = 60.0
_MAX_TIMEOUT_S = 300.0
_RETRYABLE_STATUS = frozenset({429})
_FORBIDDEN_PROFILE_KEYS = frozenset(
    {
        "apikey",
        "authorization",
        "bearertoken",
        "clientsecret",
        "headers",
        "password",
        "refreshtoken",
        "secret",
        "token",
    }
)
_RESERVED_REQUEST_KEYS = frozenset(
    {"functioncall", "functions", "messages", "model", "stream", "toolchoice", "tools"}
)
_SAFE_IDENTITY_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}\Z")
_METADATA_HOSTS = frozenset(
    {
        "instance-data",
        "instance-data.ec2.internal",
        "metadata.google.internal",
        "metadata.goog",
    }
)


class OpenAICompatibleError(RuntimeError):
    """The remote endpoint could not produce trustworthy observation evidence."""


def _normalized_key(key: str) -> str:
    return "".join(character for character in key.casefold() if character.isalnum())


def _validate_profile(value: Mapping[str, Any], *, location: str) -> dict[str, Any]:
    """Copy a JSON request profile while rejecting credentials and owned fields."""

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError(f"{location} object keys must be strings")
                if _normalized_key(key) in _FORBIDDEN_PROFILE_KEYS:
                    raise ValueError(f"{location} must not contain credentials or headers")
                visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)

    for key in value:
        if not isinstance(key, str):
            raise ValueError(f"{location} object keys must be strings")
        if _normalized_key(key) in _RESERVED_REQUEST_KEYS:
            raise ValueError(f"{location} contains an adapter-owned field")
    visit(value)
    try:
        # This simultaneously deep-copies, normalizes supported values, and rejects
        # non-finite/non-JSON evidence before it reaches a request or fingerprint.
        encoded = canonical_json(value)
    except (TypeError, ValueError):
        raise ValueError(f"{location} must be finite JSON-compatible data") from None

    decoded = json.loads(encoded)
    if not isinstance(decoded, dict):  # pragma: no cover - Mapping guarantees this
        raise ValueError(f"{location} must be a JSON object")
    return decoded


def _legacy_ipv4_address(host: str) -> ipaddress.IPv4Address | None:
    """Parse the historical inet_aton numeric forms accepted by many resolvers."""
    if not host.isascii() or re.fullmatch(r"[0-9A-Fa-fxX.]+", host) is None:
        return None
    parts = host.split(".")
    if not 1 <= len(parts) <= 4 or any(not part for part in parts):
        return None

    def component(raw: str) -> int:
        if raw.casefold().startswith("0x"):
            return int(raw[2:], 16)
        if len(raw) > 1 and raw.startswith("0"):
            return int(raw, 8)
        return int(raw, 10)

    try:
        values = [component(part) for part in parts]
    except ValueError:
        return None
    widths = {
        1: (32,),
        2: (8, 24),
        3: (8, 8, 16),
        4: (8, 8, 8, 8),
    }[len(values)]
    if any(value < 0 or value >= 2**width for value, width in zip(values, widths, strict=True)):
        return None
    numeric = 0
    for value, width in zip(values, widths, strict=True):
        numeric = (numeric << width) | value
    return ipaddress.IPv4Address(numeric)


def _normalize_endpoint(endpoint: str) -> str:
    raw = endpoint.strip()
    if not raw or "\x00" in raw:
        raise ValueError("endpoint must be non-blank and contain no NUL bytes")
    try:
        url = httpx.URL(raw)
    except (TypeError, ValueError, httpx.InvalidURL):
        raise ValueError("endpoint must be a valid HTTP(S) URL") from None
    if url.scheme not in {"http", "https"} or not url.host:
        raise ValueError("endpoint must be an absolute HTTP(S) URL")
    if url.username or url.password or url.query or url.fragment:
        raise ValueError("endpoint must not contain credentials, query, or fragment")
    host = url.host.rstrip(".").casefold()
    if host in _METADATA_HOSTS:
        raise ValueError("endpoint must not target a cloud metadata service")
    address: ipaddress.IPv4Address | ipaddress.IPv6Address | None = None
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # Resolvers may accept decimal, hexadecimal, octal, and shortened IPv4
        # forms. Parse them locally without performing a DNS lookup.
        address = _legacy_ipv4_address(host)
    mapped = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) else None
    if address is not None and (
        address.is_link_local
        or bool(mapped and mapped.is_link_local)
        or address == ipaddress.IPv6Address("fd00:ec2::254")
    ):
        raise ValueError("endpoint must not target a link-local metadata address")
    return str(url).rstrip("/")


def _validate_identity_label(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _SAFE_IDENTITY_LABEL.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be 1-128 safe ASCII identifier characters")
    return value


def _chat_completions_url(endpoint: str) -> str:
    if endpoint.endswith("/chat/completions"):
        return endpoint
    return f"{endpoint}/chat/completions"


def _messages(case: EvalCase, *, case_label: str) -> list[dict[str, Any]]:
    if isinstance(case.input, str):
        return [{"role": "user", "content": case.input}]
    if not isinstance(case.input, (list, tuple)) or not case.input:
        raise OpenAICompatibleError(
            f"{case_label} input must be text or a non-empty messages array"
        )

    messages: list[dict[str, Any]] = []
    for index, item in enumerate(case.input):
        if not isinstance(item, Mapping):
            raise OpenAICompatibleError(f"{case_label} message {index} must be an object")
        role = item.get("role")
        if not isinstance(role, str) or not role.strip() or "content" not in item:
            raise OpenAICompatibleError(f"{case_label} message {index} requires role and content")
        try:
            normalized = _validate_message(item)
        except (TypeError, ValueError) as error:
            raise OpenAICompatibleError(
                f"{case_label} message {index} must be finite JSON-compatible data"
            ) from error
        messages.append(normalized)
    return messages


def _validate_message(message: Mapping[str, Any]) -> dict[str, Any]:
    encoded = canonical_json(message)
    decoded = json.loads(encoded)
    if not isinstance(decoded, dict):  # pragma: no cover - Mapping guarantees this
        raise TypeError("message must be an object")
    return decoded


def _retry_delay(response: httpx.Response | None, *, cap_s: float) -> float:
    if response is None or cap_s == 0:
        return 0.0
    raw = response.headers.get("Retry-After")
    if raw is None:
        return 0.0
    try:
        seconds = float(raw)
    except ValueError:
        try:
            target = parsedate_to_datetime(raw)
            if target.tzinfo is None:
                target = target.replace(tzinfo=UTC)
            seconds = (target - datetime.now(UTC)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return 0.0
    if seconds != seconds:  # NaN
        return 0.0
    return min(max(seconds, 0.0), cap_s)


def _contains_any_secret(value: Any, secrets: tuple[str, ...]) -> bool:
    """Scan every JSON string, including object keys, without rendering the value."""
    if isinstance(value, str):
        return any(secret in value for secret in secrets)
    if isinstance(value, Mapping):
        return any(
            _contains_any_secret(key, secrets) or _contains_any_secret(item, secrets)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_any_secret(item, secrets) for item in value)
    return False


def _read_bounded_response(
    response: httpx.Response,
    *,
    max_bytes: int,
    deadline: float,
    case_label: str,
) -> bytes:
    """Read an identity-encoded body without ever buffering beyond its evidence cap."""
    if time.perf_counter() >= deadline:
        raise OpenAICompatibleError(f"{case_label} exceeded the cumulative elapsed-time limit")
    content_encoding = response.headers.get("Content-Encoding", "").strip().casefold()
    if content_encoding not in {"", "identity"}:
        raise OpenAICompatibleError(
            f"remote endpoint used unsupported content encoding for {case_label}"
        )
    content_length = response.headers.get("Content-Length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError:
            declared_length = -1
        if declared_length > max_bytes:
            raise OpenAICompatibleError(
                f"remote endpoint response exceeded the evidence size limit for {case_label}"
            )

    if response.is_stream_consumed:
        # Mock/custom transports may return an already-materialized response. Real
        # network transports remain streaming because this adapter uses client.stream.
        body_bytes = response.content
        if time.perf_counter() >= deadline:
            raise OpenAICompatibleError(f"{case_label} exceeded the cumulative elapsed-time limit")
        if len(body_bytes) > max_bytes:
            raise OpenAICompatibleError(
                f"remote endpoint response exceeded the evidence size limit for {case_label}"
            )
        return body_bytes

    body = bytearray()
    for chunk in response.iter_raw():
        if time.perf_counter() >= deadline:
            raise OpenAICompatibleError(f"{case_label} exceeded the cumulative elapsed-time limit")
        if len(body) + len(chunk) > max_bytes:
            raise OpenAICompatibleError(
                f"remote endpoint response exceeded the evidence size limit for {case_label}"
            )
        body.extend(chunk)
    return bytes(body)


class OpenAICompatibleAdapter:
    """Run chat completions with bounded retries and secret-free provenance.

    ``max_retries`` counts retries after the first attempt. Transport retries can
    repeat a request whose server-side outcome is unknown, so the default is one.
    """

    def __init__(
        self,
        endpoint: str,
        model: str,
        *,
        api_key: str | None = None,
        request_profile: Mapping[str, Any] | None = None,
        timeout_s: float = 30.0,
        max_retries: int = 1,
        retry_after_cap_s: float = 5.0,
        max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES,
        max_elapsed_s: float = 120.0,
        credential_scope: str | None = None,
        deployment_revision: str | None = None,
        allow_insecure_http: bool = False,
        transport: httpx.BaseTransport | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        if not model.strip() or "\x00" in model:
            raise ValueError("model must be non-blank and contain no NUL bytes")
        if api_key is not None and (
            not isinstance(api_key, str) or not api_key or "\r" in api_key or "\n" in api_key
        ):
            raise ValueError("api_key must be a non-empty string containing no newlines")
        if (
            not isinstance(timeout_s, (int, float))
            or not math.isfinite(timeout_s)
            or not 0 < timeout_s <= _MAX_TIMEOUT_S
        ):
            raise ValueError(f"timeout_s must be finite and in (0, {_MAX_TIMEOUT_S}]")
        if (
            isinstance(max_retries, bool)
            or not isinstance(max_retries, int)
            or not 0 <= max_retries <= _MAX_RETRIES
        ):
            raise ValueError(f"max_retries must be an integer in [0, {_MAX_RETRIES}]")
        if (
            not isinstance(retry_after_cap_s, (int, float))
            or not math.isfinite(retry_after_cap_s)
            or not 0 <= retry_after_cap_s <= _MAX_RETRY_AFTER_CAP_S
        ):
            raise ValueError(
                f"retry_after_cap_s must be finite and in [0, {_MAX_RETRY_AFTER_CAP_S}]"
            )
        if (
            isinstance(max_response_bytes, bool)
            or not isinstance(max_response_bytes, int)
            or not 1 <= max_response_bytes <= _MAX_CONFIGURED_RESPONSE_BYTES
        ):
            raise ValueError(
                f"max_response_bytes must be an integer in [1, {_MAX_CONFIGURED_RESPONSE_BYTES}]"
            )
        if (
            not isinstance(max_elapsed_s, (int, float))
            or not math.isfinite(max_elapsed_s)
            or not 0 < max_elapsed_s <= _MAX_ELAPSED_S
        ):
            raise ValueError(f"max_elapsed_s must be finite and in (0, {_MAX_ELAPSED_S}]")
        if client is not None and transport is not None:
            raise ValueError("client and transport are mutually exclusive")
        if not isinstance(allow_insecure_http, bool):
            raise ValueError("allow_insecure_http must be a boolean")
        if client is not None and client.follow_redirects:
            raise ValueError("custom clients must disable redirect following")

        self._endpoint = _normalize_endpoint(endpoint)
        if (
            api_key is not None
            and httpx.URL(self._endpoint).scheme == "http"
            and not allow_insecure_http
        ):
            raise ValueError(
                "api_key transmission requires HTTPS unless allow_insecure_http is explicitly set"
            )
        self._model = model.strip()
        self._credential_scope = _validate_identity_label(
            credential_scope, field_name="credential_scope"
        )
        self._deployment_revision = _validate_identity_label(
            deployment_revision, field_name="deployment_revision"
        )
        self._api_key = api_key
        self._response_secrets = (api_key, f"Bearer {api_key}") if api_key is not None else ()
        self._request_profile = _validate_profile(request_profile or {}, location="request_profile")
        if self._response_secrets and any(
            _contains_any_secret(value, self._response_secrets)
            for value in (
                self._endpoint,
                self._model,
                self._request_profile,
                self._credential_scope,
                self._deployment_revision,
            )
            if value is not None
        ):
            raise ValueError("public adapter configuration failed secret-safety validation")
        self._timeout_s = float(timeout_s)
        self._max_retries = max_retries
        self._retry_after_cap_s = float(retry_after_cap_s)
        self._max_response_bytes = max_response_bytes
        self._max_elapsed_s = float(max_elapsed_s)
        self._transport = transport
        self._client = client

        identity = {
            "adapter": "openai-compatible",
            "adapter_version": _ADAPTER_VERSION,
            "credential_scope": self._credential_scope,
            "deployment_revision": self._deployment_revision,
            "endpoint": self._endpoint,
            "allow_insecure_http": allow_insecure_http,
            "execution": {
                "max_retries": self._max_retries,
                "max_response_bytes": self._max_response_bytes,
                "max_elapsed_s": self._max_elapsed_s,
                "retry_after_cap_s": self._retry_after_cap_s,
                "timeout_s": self._timeout_s,
            },
            "model": self._model,
            "request_profile": self._request_profile,
        }
        self._adapter_fingerprint = fingerprint(identity, namespace="adapter-config")
        snapshot_digest = fingerprint(identity, namespace="model-snapshot")
        snapshot_labels = {
            "adapter": "openai-compatible",
            "adapter_version": _ADAPTER_VERSION,
            "cache_scope": (
                "revision-bound" if self._deployment_revision is not None else "ephemeral-required"
            ),
            "credential_scope": self._credential_scope or "unspecified",
            "identity_scope": "declared-remote-config",
            "model": self._model,
            "source_mutability": "provider-managed",
        }
        self._snapshot = ModelSnapshot(
            id=f"m2riv:sha256:{snapshot_digest}",
            source=ModelRef(
                uri=f"openai-compatible:{self._endpoint}",
                revision=self._deployment_revision,
            ),
            model_family=ModelFamily.LLM,
            config_fingerprint=self._adapter_fingerprint,
            runtime_profile=RuntimeProfile(parameters=self._request_profile),
            labels=snapshot_labels,
            capabilities=frozenset(),
            evidence_access=EvidenceAccess.OUTPUTS,
        )

    @property
    def adapter_fingerprint(self) -> str:
        """Stable cache identity for the non-secret adapter configuration."""
        return self._adapter_fingerprint

    def describe(self) -> ModelSnapshot:
        return self._snapshot

    def capabilities(self) -> frozenset[AdapterCapability]:
        # Requests are sequential and this implementation only accepts text content.
        return frozenset()

    def run(
        self,
        cases: Sequence[EvalCase],
        profile: RuntimeProfile,
    ) -> tuple[Observation, ...]:
        runtime_parameters = _validate_profile(
            profile.parameters, location="runtime profile parameters"
        )
        if self._response_secrets and _contains_any_secret(
            runtime_parameters, self._response_secrets
        ):
            raise OpenAICompatibleError("runtime profile failed secret-safety validation")
        if self._client is not None:
            return self._run_with_client(self._client, cases, profile, runtime_parameters)
        with httpx.Client(
            transport=self._transport,
            timeout=self._timeout_s,
            follow_redirects=False,
        ) as client:
            return self._run_with_client(client, cases, profile, runtime_parameters)

    def _run_with_client(
        self,
        client: httpx.Client,
        cases: Sequence[EvalCase],
        profile: RuntimeProfile,
        runtime_parameters: dict[str, Any],
    ) -> tuple[Observation, ...]:
        observations: list[Observation] = []
        for index, case in enumerate(cases, start=1):
            case_label = f"case #{index}"
            if self._response_secrets and _contains_any_secret(
                {"case_id": case.case_id, "input": case.input}, self._response_secrets
            ):
                raise OpenAICompatibleError(
                    f"evaluation case failed secret-safety validation for {case_label}"
                )
            messages = _messages(case, case_label=case_label)
            body = copy.deepcopy(self._request_profile)
            body.update(copy.deepcopy(runtime_parameters))
            body.update({"model": self._model, "messages": messages})
            observations.append(
                self._request_case(client, case, profile, body, case_label=case_label)
            )
        return tuple(observations)

    def _request_case(
        self,
        client: httpx.Client,
        case: EvalCase,
        profile: RuntimeProfile,
        body: dict[str, Any],
        *,
        case_label: str,
    ) -> Observation:
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Content-Type": "application/json",
        }
        if self._api_key is not None:
            headers["Authorization"] = f"Bearer {self._api_key}"

        started = time.perf_counter()
        deadline = started + self._max_elapsed_s
        attempt_latencies: list[float] = []
        response: httpx.Response | None = None
        response_body: bytes | None = None
        attempts = 0
        for attempt in range(self._max_retries + 1):
            remaining_s = deadline - time.perf_counter()
            if remaining_s <= 0:
                raise OpenAICompatibleError(
                    f"{case_label} exceeded the cumulative elapsed-time limit"
                )
            attempts = attempt + 1
            attempt_started = time.perf_counter()
            try:
                with client.stream(
                    "POST",
                    _chat_completions_url(self._endpoint),
                    json=body,
                    headers=headers,
                    timeout=min(self._timeout_s, remaining_s),
                ) as streamed_response:
                    response = streamed_response
                    if 200 <= response.status_code < 300:
                        response_body = _read_bounded_response(
                            response,
                            max_bytes=self._max_response_bytes,
                            deadline=deadline,
                            case_label=case_label,
                        )
            except httpx.TransportError:
                attempt_latencies.append(round((time.perf_counter() - attempt_started) * 1000, 3))
                if time.perf_counter() >= deadline:
                    raise OpenAICompatibleError(
                        f"{case_label} exceeded the cumulative elapsed-time limit"
                    ) from None
                if attempt == self._max_retries:
                    raise OpenAICompatibleError(
                        f"remote transport failed for {case_label} after {attempts} attempts"
                    ) from None
                continue

            attempt_latencies.append(round((time.perf_counter() - attempt_started) * 1000, 3))
            retryable = (
                response.status_code in _RETRYABLE_STATUS or 500 <= response.status_code < 600
            )
            if retryable and attempt < self._max_retries:
                delay = _retry_delay(response, cap_s=self._retry_after_cap_s)
                if delay:
                    if delay >= deadline - time.perf_counter():
                        raise OpenAICompatibleError(
                            f"{case_label} exceeded the cumulative elapsed-time limit"
                        )
                    time.sleep(delay)
                continue
            break

        if response is None:  # pragma: no cover - loop always responds or raises
            raise OpenAICompatibleError(f"remote transport failed for {case_label}")
        if time.perf_counter() >= deadline:
            raise OpenAICompatibleError(f"{case_label} exceeded the cumulative elapsed-time limit")
        if not 200 <= response.status_code < 300:
            raise OpenAICompatibleError(
                f"remote endpoint returned HTTP {response.status_code} for {case_label} "
                f"after {attempts} attempts"
            )
        if response_body is None:  # pragma: no cover - successful responses are read above
            raise OpenAICompatibleError(
                f"remote endpoint returned no response evidence for {case_label}"
            )

        try:
            payload = parse_strict_json(response_body)
        except StrictJSONError:
            raise OpenAICompatibleError(
                f"remote endpoint returned invalid JSON for {case_label}"
            ) from None
        if time.perf_counter() >= deadline:
            raise OpenAICompatibleError(f"{case_label} exceeded the cumulative elapsed-time limit")
        if self._response_secrets and _contains_any_secret(payload, self._response_secrets):
            raise OpenAICompatibleError(
                f"remote endpoint response failed secret-safety validation for {case_label}"
            )
        content, usage = self._extract_evidence(payload, case_label=case_label)
        finished = time.perf_counter()
        if finished >= deadline:
            raise OpenAICompatibleError(f"{case_label} exceeded the cumulative elapsed-time limit")
        total_latency_ms = round((finished - started) * 1000, 3)
        traces: dict[str, Any] = {
            "attempts": attempts,
            "attempt_latencies_ms": attempt_latencies,
            "latency_ms": total_latency_ms,
        }
        if usage is not None:
            traces["usage"] = usage

        output_digest = fingerprint(content, namespace="observation-output")
        try:
            return Observation(
                id=observation_content_id(
                    snapshot_id=self._snapshot.id,
                    case_id=case.case_id,
                    seed=profile.seed,
                    output_digest=output_digest,
                ),
                snapshot_id=self._snapshot.id,
                case_id=case.case_id,
                attempt=attempts - 1,
                seed=profile.seed,
                output=content,
                output_digest=output_digest,
                latency_ms=total_latency_ms,
                traces=traces,
            )
        except ValueError:
            raise OpenAICompatibleError(
                f"remote endpoint returned invalid evidence for {case_label}"
            ) from None

    @staticmethod
    def _extract_evidence(payload: Any, *, case_label: str) -> tuple[str, dict[str, Any] | None]:
        if not isinstance(payload, dict):
            raise OpenAICompatibleError(
                f"remote endpoint returned a non-object response for {case_label}"
            )
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise OpenAICompatibleError(
                f"remote endpoint response has no valid choice for {case_label}"
            )
        message = choices[0].get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise OpenAICompatibleError(
                f"remote endpoint response is missing text content for {case_label}"
            )
        usage = payload.get("usage")
        if usage is not None and not isinstance(usage, dict):
            raise OpenAICompatibleError(
                f"remote endpoint response has invalid usage for {case_label}"
            )
        if usage is not None:
            try:
                encoded_usage = canonical_json(usage)
                normalized_usage = json.loads(encoded_usage)
            except (TypeError, ValueError):
                raise OpenAICompatibleError(
                    f"remote endpoint response has invalid usage for {case_label}"
                ) from None
            if not isinstance(normalized_usage, dict):  # pragma: no cover
                raise OpenAICompatibleError(
                    f"remote endpoint response has invalid usage for {case_label}"
                )
            usage = normalized_usage
        return message["content"], usage
