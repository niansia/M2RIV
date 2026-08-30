from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from typer.testing import CliRunner

from merriv.adapters import FakeAdapter, RecordedAdapter
from merriv.cli import app
from merriv.core.identity import build_local_snapshot
from merriv.core.models import EvalCase, ModelSnapshot, RuntimeProfile
from merriv.engine import ObservationCache, PairedCaseResult
from merriv.gate import GatePolicy, GateRule, GateStatus, MetricDirection
from merriv.pipeline import compare_release

runner = CliRunner()


@dataclass(frozen=True, slots=True)
class OutputLengthMetric:
    id: str = "output_length"
    direction: MetricDirection = MetricDirection.LOWER_IS_BETTER
    binary: bool = False
    unit: str = "characters"

    def sample(self, pair: PairedCaseResult) -> tuple[float, float]:
        return float(len(pair.baseline.output)), float(len(pair.candidate.output))


def _recorded_pair(root: Path) -> tuple[RecordedAdapter, RecordedAdapter, tuple[EvalCase, ...]]:
    baseline_path = root / "baseline.jsonl"
    candidate_path = root / "candidate.jsonl"
    baseline_path.write_text(
        "".join(
            json.dumps({"case_id": f"case-{index}", "output": "a"}) + "\n" for index in range(6)
        ),
        encoding="utf-8",
    )
    candidate_path.write_text(
        "".join(
            json.dumps({"case_id": f"case-{index}", "output": "aaaa"}) + "\n" for index in range(6)
        ),
        encoding="utf-8",
    )
    cases = tuple(EvalCase(case_id=f"case-{index}", input=index) for index in range(6))
    return (
        RecordedAdapter.from_jsonl(baseline_path, build_local_snapshot(baseline_path)),
        RecordedAdapter.from_jsonl(candidate_path, build_local_snapshot(candidate_path)),
        cases,
    )


def test_custom_metric_carries_direction_and_unit_into_gate_and_report(
    tmp_path: Path,
) -> None:
    baseline, candidate, cases = _recorded_pair(tmp_path)
    result = compare_release(
        baseline=baseline,
        candidate=candidate,
        cases=cases,
        policy=GatePolicy(
            policy_id="length-policy",
            rules=(
                GateRule(
                    rule_id="length-regression",
                    metric="output_length",
                    direction=MetricDirection.LOWER_IS_BETTER,
                    margin=1,
                    min_pairs=6,
                ),
            ),
        ),
        cache=ObservationCache(tmp_path / "cache"),
        baseline_adapter_fingerprint="recorded-baseline",
        candidate_adapter_fingerprint="recorded-candidate",
        metrics=(OutputLengthMetric(),),
        resamples=100,
    )

    assert result.gate.status is GateStatus.BLOCK
    metric = result.report.metrics[0]
    assert metric.direction == "lower_is_better"
    assert metric.unit == "characters"
    assert metric.delta == 3


def test_bisect_cli_reports_first_failing_checkpoint(tmp_path: Path) -> None:
    manifest = tmp_path / "checkpoints.jsonl"
    manifest.write_text(
        "".join(
            json.dumps({"checkpoint": name, "status": status}) + "\n"
            for name, status in (
                ("rev-a", "pass"),
                ("rev-b", "pass"),
                ("rev-c", "block"),
                ("rev-d", "block"),
            )
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["bisect", str(manifest)])

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["outcome"] == "first_failing"
    assert payload["first_failing_index"] == 2
    assert payload["first_failing_checkpoint"] == "rev-c"
    assert len(payload["evaluations"]) <= 4


class _ApiFake:
    def __init__(self, delegate: FakeAdapter, fingerprint: str) -> None:
        self._delegate = delegate
        self.adapter_fingerprint = fingerprint

    def describe(self) -> ModelSnapshot:
        return self._delegate.describe()

    def capabilities(self):  # type checked through the production protocol
        return self._delegate.capabilities()

    def run(self, cases: tuple[EvalCase, ...], profile: RuntimeProfile):
        return self._delegate.run(cases, profile)


def test_compare_api_cli_uses_environment_secrets_without_printing_them(
    tmp_path: Path, monkeypatch
) -> None:
    suite = tmp_path / "suite.jsonl"
    policy = tmp_path / "policy.yaml"
    baseline_artifact = tmp_path / "baseline.bin"
    candidate_artifact = tmp_path / "candidate.bin"
    baseline_artifact.write_bytes(b"baseline")
    candidate_artifact.write_bytes(b"candidate")
    suite.write_text(
        "".join(
            json.dumps({"case_id": f"case-{index}", "input": "q", "expected": "ok"}) + "\n"
            for index in range(4)
        ),
        encoding="utf-8",
    )
    policy.write_text(
        """schema_version: 1.0.0
policy_id: api-release
multiple_comparison_method: none
rules:
  - rule_id: quality
    metric: accuracy
    margin: 0
    min_pairs: 4
""",
        encoding="utf-8",
    )
    responses = {f"case-{index}": "ok" for index in range(4)}
    adapters = {
        "https://baseline.test/v1": _ApiFake(
            FakeAdapter(build_local_snapshot(baseline_artifact), responses), "baseline-api"
        ),
        "https://candidate.test/v1": _ApiFake(
            FakeAdapter(build_local_snapshot(candidate_artifact), responses), "candidate-api"
        ),
    }
    secrets_seen: list[str | None] = []

    def adapter_factory(endpoint: str, _model: str, **kwargs):
        secrets_seen.append(kwargs.get("api_key"))
        return adapters[endpoint]

    monkeypatch.setattr("merriv.cli.OpenAICompatibleAdapter", adapter_factory)
    secret = "sk-cli-secret-canary"
    result = runner.invoke(
        app,
        [
            "compare-api",
            "https://baseline.test/v1",
            "https://candidate.test/v1",
            "--baseline-model",
            "base",
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
        env={
            "MERRIV_BASELINE_API_KEY": secret,
            "MERRIV_CANDIDATE_API_KEY": secret,
        },
    )

    assert result.exit_code == 0
    assert secrets_seen == [secret, secret]
    assert secret not in result.stdout
    assert secret not in result.stderr
    assert "EVALUATION DECISION: PASS" in result.stdout
