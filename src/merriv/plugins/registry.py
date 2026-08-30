"""In-process explicit plugin registry with collision-safe metric ownership."""

from __future__ import annotations

from dataclasses import dataclass

from merriv.adapters import AdapterCapability, ModelAdapter
from merriv.core.models import ModelSnapshot, PluginRecord
from merriv.execution import ExecutionBackend, ExecutorDescriptor
from merriv.gate import MetricDirection
from merriv.metrics import PairedMetric
from merriv.plugins.models import PluginKind, PluginManifest


class PluginRegistrationError(ValueError):
    """A plugin declaration is incompatible, unsafe, or ambiguous."""


MAX_REGISTERED_METRICS = 256
MAX_REGISTERED_PLUGINS = 128
MAX_REGISTERED_EXECUTORS = 64
MAX_REGISTERED_ADAPTERS = 128


@dataclass(frozen=True, slots=True)
class RegisteredMetric:
    manifest: PluginManifest
    metric: PairedMetric
    declaration: MetricDeclaration


@dataclass(frozen=True, slots=True)
class MetricDeclaration:
    metric_id: str
    direction: MetricDirection
    binary: bool
    unit: str


@dataclass(frozen=True, slots=True)
class RegisteredExecutor:
    manifest: PluginManifest
    executor: ExecutionBackend
    descriptor: ExecutorDescriptor


@dataclass(frozen=True, slots=True)
class RegisteredAdapter:
    manifest: PluginManifest
    adapter_id: str
    adapter: ModelAdapter
    snapshot_id: str
    config_fingerprint: str
    capabilities: frozenset[AdapterCapability]


def _safe_registry_id(value: str, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or not value[0].isalnum()
        or any(
            not (character.isascii() and (character.isalnum() or character in "._-"))
            for character in value
        )
    ):
        raise PluginRegistrationError(f"{label} must be a safe bounded ASCII identifier")
    return value


def _validate_metric(metric: PairedMetric) -> MetricDeclaration:
    metric_id = metric.id
    direction = metric.direction
    binary = metric.binary
    unit = metric.unit
    sample = metric.sample
    if (
        not isinstance(metric_id, str)
        or not metric_id
        or len(metric_id) > 128
        or not metric_id[0].isalnum()
        or any(
            not (character.isascii() and (character.isalnum() or character in "._-"))
            for character in metric_id
        )
    ):
        raise PluginRegistrationError(
            "metric id must be a safe ASCII identifier using letters, digits, '.', '_', or '-'"
        )
    if not isinstance(direction, MetricDirection):
        raise PluginRegistrationError("metric direction must be a MetricDirection")
    if not isinstance(binary, bool):
        raise PluginRegistrationError("metric binary flag must be boolean")
    if (
        not isinstance(unit, str)
        or not unit.strip()
        or len(unit) > 64
        or any(not character.isascii() or not 32 <= ord(character) <= 126 for character in unit)
    ):
        raise PluginRegistrationError("metric unit must be non-blank, bounded text")
    if not callable(sample):
        raise PluginRegistrationError("metric sample must be callable")
    return MetricDeclaration(metric_id, direction, binary, unit)


class PluginRegistry:
    """Register already-instantiated trusted plugins without dynamic imports."""

    def __init__(self) -> None:
        self._metrics: dict[str, RegisteredMetric] = {}
        self._executors: dict[str, RegisteredExecutor] = {}
        self._adapters: dict[str, RegisteredAdapter] = {}
        self._manifests: dict[tuple[str, PluginKind], PluginManifest] = {}

    def _register_manifest(self, manifest: PluginManifest) -> None:
        plugin_key = (manifest.name, manifest.kind)
        existing_manifest = self._manifests.get(plugin_key)
        if existing_manifest is not None and existing_manifest != manifest:
            raise PluginRegistrationError(
                f"plugin {manifest.name!r} was registered with conflicting identity"
            )
        if existing_manifest is None and len(self._manifests) >= MAX_REGISTERED_PLUGINS:
            raise PluginRegistrationError("plugin registry capacity exceeded")
        self._manifests[plugin_key] = manifest

    def register_metric(self, manifest: PluginManifest, metric: PairedMetric) -> RegisteredMetric:
        if manifest.kind is not PluginKind.METRIC:
            raise PluginRegistrationError("a metric requires a metric plugin manifest")
        if len(self._metrics) >= MAX_REGISTERED_METRICS:
            raise PluginRegistrationError("metric registry capacity exceeded")
        try:
            declaration = _validate_metric(metric)
        except Exception:
            raise PluginRegistrationError("metric declaration is invalid") from None
        existing_metric = self._metrics.get(declaration.metric_id)
        if existing_metric is not None:
            raise PluginRegistrationError(
                f"metric id {declaration.metric_id!r} is already registered"
            )
        self._register_manifest(manifest)
        registration = RegisteredMetric(
            manifest=manifest,
            metric=metric,
            declaration=declaration,
        )
        self._metrics[declaration.metric_id] = registration
        return registration

    def register_adapter(
        self,
        manifest: PluginManifest,
        adapter_id: str,
        adapter: ModelAdapter,
    ) -> RegisteredAdapter:
        if manifest.kind is not PluginKind.ADAPTER:
            raise PluginRegistrationError("an adapter requires an adapter plugin manifest")
        if not isinstance(adapter, ModelAdapter):
            raise PluginRegistrationError("adapter does not implement ModelAdapter")
        if len(self._adapters) >= MAX_REGISTERED_ADAPTERS:
            raise PluginRegistrationError("adapter registry capacity exceeded")
        normalized_id = _safe_registry_id(adapter_id, label="adapter id")
        if normalized_id in self._adapters:
            raise PluginRegistrationError(f"adapter id {normalized_id!r} is already registered")
        try:
            snapshot = ModelSnapshot.model_validate(adapter.describe())
            capabilities = frozenset(adapter.capabilities())
        except Exception:
            raise PluginRegistrationError("adapter declaration is invalid") from None
        if any(not isinstance(item, AdapterCapability) for item in capabilities):
            raise PluginRegistrationError("adapter capabilities are invalid")
        if snapshot.config_fingerprint is None:
            raise PluginRegistrationError("adapter snapshot requires a config fingerprint")
        if snapshot.config_fingerprint != manifest.config_fingerprint:
            raise PluginRegistrationError(
                "adapter manifest and snapshot config fingerprints must match"
            )
        if not frozenset(item.value for item in capabilities).issubset(manifest.capabilities):
            raise PluginRegistrationError("adapter capabilities exceed its plugin manifest")
        self._register_manifest(manifest)
        registration = RegisteredAdapter(
            manifest=manifest,
            adapter_id=normalized_id,
            adapter=adapter,
            snapshot_id=snapshot.id,
            config_fingerprint=snapshot.config_fingerprint,
            capabilities=capabilities,
        )
        self._adapters[normalized_id] = registration
        return registration

    def register_executor(
        self, manifest: PluginManifest, executor: ExecutionBackend
    ) -> RegisteredExecutor:
        if manifest.kind is not PluginKind.EXECUTOR:
            raise PluginRegistrationError("an executor requires an executor plugin manifest")
        if not isinstance(executor, ExecutionBackend):
            raise PluginRegistrationError("executor does not implement ExecutionBackend")
        if len(self._executors) >= MAX_REGISTERED_EXECUTORS:
            raise PluginRegistrationError("executor registry capacity exceeded")
        try:
            descriptor = ExecutorDescriptor.model_validate(executor.describe())
        except Exception:
            raise PluginRegistrationError("executor descriptor is invalid") from None
        if descriptor.executor_id in self._executors:
            raise PluginRegistrationError(
                f"executor id {descriptor.executor_id!r} is already registered"
            )
        if descriptor.config_fingerprint != manifest.config_fingerprint:
            raise PluginRegistrationError(
                "executor manifest and descriptor config fingerprints must match"
            )
        if not descriptor.capabilities.issubset(manifest.capabilities):
            raise PluginRegistrationError(
                "executor descriptor capabilities exceed its plugin manifest"
            )
        self._register_manifest(manifest)
        registration = RegisteredExecutor(manifest, executor, descriptor)
        self._executors[descriptor.executor_id] = registration
        return registration

    @staticmethod
    def _assert_unchanged(registration: RegisteredMetric) -> None:
        try:
            current = _validate_metric(registration.metric)
        except Exception:
            raise PluginRegistrationError("registered metric declaration became invalid") from None
        if current != registration.declaration:
            raise PluginRegistrationError(
                "registered metric declaration changed after registration"
            )

    def metric(self, metric_id: str) -> RegisteredMetric:
        try:
            registration = self._metrics[metric_id]
        except KeyError as error:
            raise PluginRegistrationError(f"metric id {metric_id!r} is not registered") from error
        self._assert_unchanged(registration)
        return registration

    def metrics(self) -> tuple[PairedMetric, ...]:
        registrations = tuple(registration for _, registration in sorted(self._metrics.items()))
        for registration in registrations:
            self._assert_unchanged(registration)
        return tuple(registration.metric for registration in registrations)

    @staticmethod
    def _assert_executor_unchanged(registration: RegisteredExecutor) -> None:
        try:
            current = ExecutorDescriptor.model_validate(registration.executor.describe())
        except Exception:
            raise PluginRegistrationError("registered executor descriptor became invalid") from None
        if current != registration.descriptor:
            raise PluginRegistrationError(
                "registered executor descriptor changed after registration"
            )

    def executor(self, executor_id: str) -> RegisteredExecutor:
        try:
            registration = self._executors[executor_id]
        except KeyError as error:
            raise PluginRegistrationError(
                f"executor id {executor_id!r} is not registered"
            ) from error
        self._assert_executor_unchanged(registration)
        return registration

    def executors(self) -> tuple[ExecutionBackend, ...]:
        registrations = tuple(registration for _, registration in sorted(self._executors.items()))
        for registration in registrations:
            self._assert_executor_unchanged(registration)
        return tuple(registration.executor for registration in registrations)

    @staticmethod
    def _assert_adapter_unchanged(registration: RegisteredAdapter) -> None:
        try:
            snapshot = ModelSnapshot.model_validate(registration.adapter.describe())
            capabilities = frozenset(registration.adapter.capabilities())
        except Exception:
            raise PluginRegistrationError("registered adapter declaration became invalid") from None
        if (
            snapshot.id != registration.snapshot_id
            or snapshot.config_fingerprint != registration.config_fingerprint
            or capabilities != registration.capabilities
        ):
            raise PluginRegistrationError(
                "registered adapter declaration changed after registration"
            )

    def adapter(self, adapter_id: str) -> RegisteredAdapter:
        try:
            registration = self._adapters[adapter_id]
        except KeyError as error:
            raise PluginRegistrationError(f"adapter id {adapter_id!r} is not registered") from error
        self._assert_adapter_unchanged(registration)
        return registration

    def adapters(self) -> tuple[ModelAdapter, ...]:
        registrations = tuple(registration for _, registration in sorted(self._adapters.items()))
        for registration in registrations:
            self._assert_adapter_unchanged(registration)
        return tuple(registration.adapter for registration in registrations)

    def plugin_records(self) -> tuple[PluginRecord, ...]:
        return tuple(
            PluginRecord(
                name=manifest.name,
                version=manifest.version,
                kind=manifest.kind.value,
                api_version=manifest.api_version,
                capabilities=manifest.capabilities,
                config_fingerprint=manifest.config_fingerprint,
            )
            for _, manifest in sorted(self._manifests.items())
        )

    def metric_plugin_records(self) -> dict[str, PluginRecord]:
        for registration in self._metrics.values():
            self._assert_unchanged(registration)
        return {
            metric_id: PluginRecord(
                name=registration.manifest.name,
                version=registration.manifest.version,
                kind=registration.manifest.kind.value,
                api_version=registration.manifest.api_version,
                capabilities=registration.manifest.capabilities,
                config_fingerprint=registration.manifest.config_fingerprint,
            )
            for metric_id, registration in self._metrics.items()
        }
