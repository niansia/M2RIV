from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from merriv.adapters import (
    FakeAdapter,
    ModelAdapter,
    OpenAICompatibleError,
)
from merriv.cli import app
from merriv.core.identity import build_local_snapshot, fingerprint
from merriv.core.models import (
    EvalCase,
    EvidenceRef,
    Observation,
    PluginRecord,
    RuntimeProfile,
)
from merriv.engine import ObservationCache, PairedCaseResult, PairedRunner, RunnerContractError
from merriv.execution import ExecutionBackend, ExecutorDescriptor
from merriv.gate import GatePolicy, GateRule, MetricDirection
from merriv.metrics import ExactMatchMetric
from merriv.pipeline import MetricExecutionError, compare_release
from merriv.planning import (
    MAX_PLAN_SLICE_VALUES_PER_KEY,
    PlanCompileError,
    compile_release_plan,
)
from merriv.plugins import (
    PluginKind,
    PluginManifest,
    PluginRegistrationError,
    PluginRegistry,
    builtin_metric_registry,
)
from merriv.reports import render_markdown, write_report_bundle

runner = CliRunner()


@dataclass(frozen=True, slots=True)
class LengthMetric:
    id: str = "length"
    direction: MetricDirection = MetricDirection.LOWER_IS_BETTER
    binary: bool = False
    unit: str = "characters"

    def sample(self, pair: PairedCaseResult) -> tuple[float, float]:
        return float(len(pair.baseline.output)), float(len(pair.candidate.output))


def _manifest(name: str = "example.metrics") -> PluginManifest:
    return PluginManifest(
        name=name,
        version="1.2.0",
        kind=PluginKind.METRIC,
        config_fingerprint=fingerprint({"name": name}, namespace="test-plugin"),
        capabilities=frozenset({"length"}),
    )


def _cases() -> tuple[EvalCase, ...]:
    return tuple(
        EvalCase(
            case_id=f"case-{index}",
            input="q",
            expected="ok",
            slices={"risk": "rare" if index >= 2 else "common"},
        )
        for index in range(4)
    )


def _adapters(root: Path) -> tuple[FakeAdapter, FakeAdapter]:
    baseline_path = root / "baseline.bin"
    candidate_path = root / "candidate.bin"
    baseline_path.write_bytes(b"baseline")
    candidate_path.write_bytes(b"candidate")
    responses = {case.case_id: "ok" for case in _cases()}
    return (
        FakeAdapter(build_local_snapshot(baseline_path), responses),
        FakeAdapter(build_local_snapshot(candidate_path), responses),
    )


def test_explicit_plugin_registry_tracks_metric_ownership_without_importing() -> None:
    registry = PluginRegistry()
    registration = registry.register_metric(_manifest(), LengthMetric())

    assert registration.metric.id == "length"
    assert registry.metric("length") == registration
    assert registry.metrics() == (registration.metric,)
    assert registry.metric_plugin_records()["length"].name == "example.metrics"
    assert registry.plugin_records()[0].capabilities == frozenset({"length"})
    assert registry.plugin_records()[0].kind == "metric"
    assert registry.plugin_records()[0].api_version == "0.1"

    with pytest.raises(PluginRegistrationError, match="already registered"):
        registry.register_metric(_manifest("other.metrics"), LengthMetric())


def test_builtin_registry_has_stable_core_metric_ownership() -> None:
    registry = builtin_metric_registry()
    assert [metric.id for metric in registry.metrics()] == ["accuracy", "mean_latency_ms"]
    assert len(registry.plugin_records()) == 1
    assert registry.plugin_records()[0].name == "merriv.builtin.metrics"


def test_runtime_profile_rejects_credentials_before_identity_hashing() -> None:
    with pytest.raises(ValidationError, match="credentials or headers"):
        RuntimeProfile(parameters={"nested": {"api_key": "sk-never-hash"}})
    assert RuntimeProfile(parameters={"max_tokens": 128}).parameters == {"max_tokens": 128}


def test_registry_rejects_wrong_kind_and_unsafe_manifest() -> None:
    wrong_kind = PluginManifest(
        name="example.adapter",
        version="1.0.0",
        kind=PluginKind.ADAPTER,
        config_fingerprint=fingerprint("adapter", namespace="test-plugin"),
    )
    with pytest.raises(PluginRegistrationError, match="metric plugin manifest"):
        PluginRegistry().register_metric(wrong_kind, LengthMetric())
    with pytest.raises(ValidationError):
        PluginManifest(
            name="unsafe\nplugin",
            version="1.0.0",
            kind=PluginKind.METRIC,
            config_fingerprint=fingerprint("unsafe", namespace="test-plugin"),
        )


class MutableMetric:
    id = "mutable"
    direction = MetricDirection.HIGHER_IS_BETTER
    binary = False
    unit = "score"

    def sample(self, pair: PairedCaseResult) -> tuple[float, float]:
        return 1.0, 1.0


class ExplodingMetric:
    @property
    def id(self):
        raise RuntimeError("sk-declaration-secret")

    direction = MetricDirection.HIGHER_IS_BETTER
    binary = False
    unit = "score"

    def sample(self, pair: PairedCaseResult) -> tuple[float, float]:
        return 1.0, 1.0


def test_registry_detects_mutation_and_sanitizes_declaration_errors() -> None:
    registry = PluginRegistry()
    metric = MutableMetric()
    registry.register_metric(_manifest(), metric)
    metric.unit = "changed"
    with pytest.raises(PluginRegistrationError, match="changed after"):
        registry.metrics()

    with pytest.raises(PluginRegistrationError) as captured:
        PluginRegistry().register_metric(_manifest(), ExplodingMetric())
    assert "sk-declaration-secret" not in str(captured.value)
    assert captured.value.__cause__ is None


def test_compiled_plan_is_stable_and_contains_plugin_provenance() -> None:
    registry = PluginRegistry()
    registry.register_metric(_manifest(), LengthMetric())
    policy = GatePolicy(
        policy_id="release-v1",
        rules=(
            GateRule(
                rule_id="rare-length",
                metric="length@risk=rare",
                direction=MetricDirection.LOWER_IS_BETTER,
                margin=2,
                min_pairs=2,
            ),
        ),
    )
    arguments = {
        "policy": policy,
        "cases": _cases(),
        "metrics": registry.metrics(),
        "slice_keys": ("risk",),
        "metric_plugins": registry.metric_plugin_records(),
    }
    first = compile_release_plan(**arguments)
    second = compile_release_plan(**arguments)

    assert first == second
    assert first.id == second.id
    assert first.bindings[0].base_metric_id == "length"
    assert first.plugins[0].name == "example.metrics"
    rare = next(metric for metric in first.metrics if metric.metric_id == "length@risk=rare")
    assert rare.plugin_name == "example.metrics"
    assert rare.unit == "characters"

    changed_statistics = compile_release_plan(**arguments, resamples=9_999)
    changed_runtime = compile_release_plan(
        **arguments,
        runtime_profile=RuntimeProfile(seed=99),
    )
    changed_confidence = compile_release_plan(**arguments, confidence_level=0.9)
    assert (
        len(
            {
                first.id,
                changed_statistics.id,
                changed_runtime.id,
                changed_confidence.id,
            }
        )
        == 4
    )
    assert first.resamples == 2_000
    assert first.confidence_level == 0.95


def test_plan_rejects_missing_metric_direction_and_unsafe_slice_before_execution() -> None:
    cases = _cases()
    with pytest.raises(PlanCompileError, match="unavailable metric"):
        compile_release_plan(
            policy=GatePolicy(
                policy_id="missing",
                rules=(GateRule(rule_id="missing", metric="not_registered", margin=0),),
            ),
            cases=cases,
            metrics=(ExactMatchMetric(),),
        )
    with pytest.raises(PlanCompileError, match="direction"):
        compile_release_plan(
            policy=GatePolicy(
                policy_id="wrong-direction",
                rules=(
                    GateRule(
                        rule_id="wrong-direction",
                        metric="accuracy",
                        direction=MetricDirection.LOWER_IS_BETTER,
                        margin=0,
                    ),
                ),
            ),
            cases=cases,
            metrics=(ExactMatchMetric(),),
        )
    hostile_cases = (EvalCase(case_id="safe", input="q", slices={"risk": "rare\nforged"}),)
    with pytest.raises(PlanCompileError, match="slice value"):
        compile_release_plan(
            policy=GatePolicy(
                policy_id="safe",
                rules=(GateRule(rule_id="safe", metric="accuracy", margin=0),),
            ),
            cases=hostile_cases,
            metrics=(ExactMatchMetric(),),
            slice_keys=("risk",),
        )
    with pytest.raises(PlanCompileError, match="absent from every"):
        compile_release_plan(
            policy=GatePolicy(
                policy_id="missing-slice",
                rules=(GateRule(rule_id="quality", metric="accuracy", margin=0),),
            ),
            cases=cases,
            metrics=(ExactMatchMetric(),),
            slice_keys=("not_present",),
        )


def test_plan_caps_slice_cardinality_and_rejects_hostile_plugin_provenance() -> None:
    many_values = tuple(
        EvalCase(case_id=f"case-{index}", input="q", slices={"tenant": f"t{index}"})
        for index in range(MAX_PLAN_SLICE_VALUES_PER_KEY + 1)
    )
    policy = GatePolicy(
        policy_id="bounded",
        rules=(GateRule(rule_id="quality", metric="accuracy", margin=0),),
    )
    with pytest.raises(PlanCompileError, match="value capacity"):
        compile_release_plan(
            policy=policy,
            cases=many_values,
            metrics=(ExactMatchMetric(),),
            slice_keys=("tenant",),
        )
    with pytest.raises(ValidationError):
        PluginRecord(
            name="safe",
            version="1.0.0",
            capabilities=frozenset({"safe\nforged"}),
            config_fingerprint=fingerprint("hostile", namespace="test-plugin"),
        )
    incompatible = PluginRecord(
        name="safe",
        version="1.0.0",
        kind="executor",
        config_fingerprint=fingerprint("hostile", namespace="test-plugin"),
    )
    with pytest.raises(PlanCompileError, match="incompatible plugin kind"):
        compile_release_plan(
            policy=policy,
            cases=_cases(),
            metrics=(ExactMatchMetric(),),
            metric_plugins={"accuracy": incompatible},
        )


class CountingAdapter:
    def __init__(self, delegate: FakeAdapter) -> None:
        self.delegate = delegate
        self.calls = 0

    def describe(self):
        return self.delegate.describe()

    def capabilities(self):
        return self.delegate.capabilities()

    def run(self, cases: Sequence[EvalCase], profile: RuntimeProfile):
        self.calls += 1
        return self.delegate.run(cases, profile)


def test_compile_failure_happens_before_any_adapter_execution(tmp_path: Path) -> None:
    baseline_raw, candidate_raw = _adapters(tmp_path)
    baseline = CountingAdapter(baseline_raw)
    candidate = CountingAdapter(candidate_raw)
    with pytest.raises(PlanCompileError, match="unavailable metric"):
        compare_release(
            baseline=baseline,
            candidate=candidate,
            cases=_cases(),
            policy=GatePolicy(
                policy_id="missing",
                rules=(GateRule(rule_id="missing", metric="cost", margin=0),),
            ),
            cache=ObservationCache(tmp_path / "cache"),
            baseline_adapter_fingerprint="baseline",
            candidate_adapter_fingerprint="candidate",
            metrics=(ExactMatchMetric(),),
            resamples=100,
        )
    assert baseline.calls == candidate.calls == 0


def test_adapter_plugin_registration_binds_manifest_to_snapshot(tmp_path: Path) -> None:
    baseline, candidate = _adapters(tmp_path)
    adapter = CountingAdapter(baseline)
    snapshot = adapter.describe()
    assert snapshot.config_fingerprint is not None
    manifest = PluginManifest(
        name="example.adapter",
        version="1.0.0",
        kind=PluginKind.ADAPTER,
        config_fingerprint=snapshot.config_fingerprint,
        capabilities=frozenset({"batch"}),
    )
    registry = PluginRegistry()
    registration = registry.register_adapter(manifest, "baseline", adapter)

    assert registration.snapshot_id == snapshot.id
    assert registry.adapter("baseline") == registration
    assert registry.adapters() == (adapter,)

    adapter.delegate = candidate
    with pytest.raises(PluginRegistrationError, match="changed after"):
        registry.adapters()


class CountingExecutor:
    def __init__(self, label: str) -> None:
        self.label = label
        self.calls = 0

    def describe(self) -> ExecutorDescriptor:
        return ExecutorDescriptor(
            executor_id=f"test.{self.label}",
            version="1.0.0",
            config_fingerprint=fingerprint(self.label, namespace="test-executor"),
        )

    def execute(
        self,
        adapter: ModelAdapter,
        cases: Sequence[EvalCase],
        profile: RuntimeProfile,
    ) -> tuple[Observation, ...]:
        self.calls += 1
        return adapter.run(cases, profile)


def test_executor_identity_partitions_cache_and_warm_runs_dispatch_nothing(
    tmp_path: Path,
) -> None:
    baseline, candidate = _adapters(tmp_path)
    cache = ObservationCache(tmp_path / "cache")
    first_executor = CountingExecutor("first")
    first_runner = PairedRunner(
        cache,
        baseline_executor=first_executor,
        candidate_executor=first_executor,
    )
    first = first_runner.run(
        baseline,
        candidate,
        _cases(),
        profile=RuntimeProfile(),
        baseline_adapter_fingerprint="baseline",
        candidate_adapter_fingerprint="candidate",
    )
    warm = first_runner.run(
        baseline,
        candidate,
        _cases(),
        profile=RuntimeProfile(),
        baseline_adapter_fingerprint="baseline",
        candidate_adapter_fingerprint="candidate",
    )
    second_executor = CountingExecutor("second")
    PairedRunner(
        cache,
        baseline_executor=second_executor,
        candidate_executor=second_executor,
    ).run(
        baseline,
        candidate,
        _cases(),
        profile=RuntimeProfile(),
        baseline_adapter_fingerprint="baseline",
        candidate_adapter_fingerprint="candidate",
    )

    assert first_executor.calls == 2
    assert first.baseline_execution.requested_cases == 4
    assert warm.cache_hit_count == 8
    assert warm.baseline_execution.requested_cases == 0
    assert warm.baseline_execution.returned_observations == 0
    assert second_executor.calls == 2


def test_executor_plugin_registration_binds_manifest_to_descriptor() -> None:
    executor = CountingExecutor("registered")
    descriptor = executor.describe()
    manifest = PluginManifest(
        name="example.executor",
        version="1.0.0",
        kind=PluginKind.EXECUTOR,
        config_fingerprint=descriptor.config_fingerprint,
    )
    registry = PluginRegistry()
    registration = registry.register_executor(manifest, executor)

    assert registration.descriptor == descriptor
    assert registry.executor(descriptor.executor_id) == registration
    assert registry.executors() == (executor,)
    assert registry.plugin_records()[0].name == "example.executor"

    wrong_identity = manifest.model_copy(
        update={
            "name": "wrong.executor",
            "config_fingerprint": fingerprint("wrong", namespace="test-executor"),
        }
    )
    with pytest.raises(PluginRegistrationError, match="fingerprints must match"):
        PluginRegistry().register_executor(wrong_identity, executor)

    executor.label = "mutated"
    with pytest.raises(PluginRegistrationError, match="changed after"):
        registry.executors()


class HostileExecutor(CountingExecutor):
    def execute(self, adapter, cases, profile):
        raise RuntimeError("Authorization: Bearer sk-executor-secret")


class HostileDescribeExecutor(CountingExecutor):
    def describe(self):
        raise RuntimeError("Authorization: Bearer sk-describe-secret")


class MalformedDescribeExecutor(CountingExecutor):
    def describe(self):
        return {"executor_id": "sk-malformed-descriptor-secret"}


class ForgedTrustedErrorExecutor(CountingExecutor):
    def execute(self, adapter, cases, profile):
        raise OpenAICompatibleError("Authorization: Bearer sk-forged-safe-error")


@pytest.mark.parametrize(
    "executor, secret",
    [
        (HostileExecutor("hostile"), "sk-executor-secret"),
        (HostileDescribeExecutor("describe"), "sk-describe-secret"),
        (MalformedDescribeExecutor("malformed"), "sk-malformed-descriptor-secret"),
        (ForgedTrustedErrorExecutor("forged"), "sk-forged-safe-error"),
    ],
)
def test_executor_failures_are_secret_free(
    tmp_path: Path, executor: ExecutionBackend, secret: str
) -> None:
    baseline, candidate = _adapters(tmp_path)
    with pytest.raises(RunnerContractError) as captured:
        PairedRunner(
            ObservationCache(tmp_path / "cache"),
            baseline_executor=executor,
        ).run(
            baseline,
            candidate,
            _cases(),
            profile=RuntimeProfile(),
            baseline_adapter_fingerprint="baseline",
            candidate_adapter_fingerprint="candidate",
        )
    assert secret not in str(captured.value)


@dataclass(frozen=True, slots=True)
class HostileMetric:
    id: str = "hostile"
    direction: MetricDirection = MetricDirection.HIGHER_IS_BETTER
    binary: bool = False
    unit: str = "score"

    def sample(self, pair: PairedCaseResult) -> tuple[float, float]:
        raise RuntimeError("sk-metric-secret")


def test_metric_plugin_failure_is_secret_free_and_report_links_plan(tmp_path: Path) -> None:
    baseline, candidate = _adapters(tmp_path)
    arguments = {
        "baseline": baseline,
        "candidate": candidate,
        "cases": _cases(),
        "policy": GatePolicy(
            policy_id="hostile",
            rules=(GateRule(rule_id="hostile", metric="hostile", margin=0),),
        ),
        "cache": ObservationCache(tmp_path / "cache"),
        "baseline_adapter_fingerprint": "baseline",
        "candidate_adapter_fingerprint": "candidate",
        "metrics": (HostileMetric(),),
        "resamples": 100,
    }
    with pytest.raises(MetricExecutionError) as captured:
        compare_release(**arguments)
    assert "sk-metric-secret" not in str(captured.value)

    passing = compare_release(
        **{
            **arguments,
            "policy": GatePolicy(
                policy_id="quality",
                rules=(GateRule(rule_id="quality", metric="accuracy", margin=0),),
            ),
            "cache": ObservationCache(tmp_path / "passing-cache"),
            "metrics": (ExactMatchMetric(),),
            "additional_evidence": (
                EvidenceRef(
                    id="mcr:sha256:" + "1" * 64,
                    kind="artifact-diff",
                    uri="artifact-diff.json",
                ),
            ),
        }
    )
    assert passing.report.release_plan_id == passing.plan.id
    assert [execution.role for execution in passing.report.executions] == [
        "baseline",
        "candidate",
    ]
    assert all(execution.executor_id == "merriv.local" for execution in passing.report.executions)
    assert sum(execution.cache_hits for execution in passing.report.executions) == 0
    assert any(evidence.kind == "artifact-diff" for evidence in passing.report.evidence)
    markdown = render_markdown(passing.report)
    assert "## Linked evidence" in markdown
    provenance = markdown.index("## Execution provenance")
    baseline_row = markdown.index("| baseline | merriv.local")
    linked_evidence = markdown.index("## Linked evidence")
    assert provenance < baseline_row < linked_evidence
    with pytest.raises(ValueError, match="conflicting records"):
        compare_release(
            **{
                **arguments,
                "policy": GatePolicy(
                    policy_id="quality",
                    rules=(GateRule(rule_id="quality", metric="accuracy", margin=0),),
                ),
                "cache": ObservationCache(tmp_path / "conflicting-evidence-cache"),
                "metrics": (ExactMatchMetric(),),
                "additional_evidence": (
                    EvidenceRef(
                        id="mcr:sha256:" + "2" * 64,
                        kind="artifact-diff",
                        uri="first.json",
                    ),
                    EvidenceRef(
                        id="mcr:sha256:" + "2" * 64,
                        kind="artifact-diff",
                        uri="conflicting.json",
                    ),
                ),
            }
        )
    bundle = write_report_bundle(
        passing.report,
        tmp_path / "bundle",
        release_plan=passing.plan,
        evidence_manifest=passing.evidence_manifest,
    )
    assert bundle.plan_path is not None
    assert json.loads(bundle.plan_path.read_text("utf-8"))["id"] == passing.plan.id
    assert bundle.evidence_manifest_path is not None
    manifest_document = json.loads(bundle.evidence_manifest_path.read_text("utf-8"))
    assert manifest_document["id"] == passing.evidence_manifest.id
    assert len(manifest_document["sets"]) <= len(passing.report.metrics)
    assert {metric.evidence_set_id for metric in passing.report.metrics} == {
        item["id"] for item in manifest_document["sets"]
    }

    mismatched_report = passing.report.model_copy(
        update={"release_plan_id": "mcr:sha256:" + "0" * 64}
    )
    with pytest.raises(ValueError, match="identity does not match"):
        write_report_bundle(
            mismatched_report,
            tmp_path / "mismatch",
            release_plan=passing.plan,
            evidence_manifest=passing.evidence_manifest,
        )


def test_plan_cli_outputs_content_addressed_plan(tmp_path: Path) -> None:
    suite = tmp_path / "suite.jsonl"
    policy = tmp_path / "policy.yaml"
    suite.write_text(
        "".join(json.dumps(case.model_dump(mode="json")) + "\n" for case in _cases()),
        encoding="utf-8",
    )
    policy.write_text(
        """schema_version: 1.0.0
policy_id: preflight
rules:
  - rule_id: rare-quality
    metric: accuracy@risk=rare
    margin: 0.1
    min_pairs: 2
""",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        [
            "plan",
            "--suite",
            str(suite),
            "--policy",
            str(policy),
            "--slice-key",
            "risk",
        ],
    )

    assert result.exit_code == 0
    document = json.loads(result.stdout)
    assert document["id"].startswith("mcr:sha256:")
    assert document["bindings"][0]["metric_id"] == "accuracy@risk=rare"
    assert document["plugins"][0]["name"] == "merriv.builtin.metrics"
    assert document["plugins"][0]["kind"] == "metric"
    assert document["resamples"] == 2_000
