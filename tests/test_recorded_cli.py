from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree

import pytest
from typer.testing import CliRunner

from merriv.cli import app
from merriv.io import InputFormatError, load_policy, load_suite

runner = CliRunner()


def _write_fixture(root: Path, *, candidate_fails: bool = True) -> tuple[Path, Path, Path, Path]:
    suite = root / "suite.jsonl"
    baseline = root / "baseline.jsonl"
    candidate = root / "candidate.jsonl"
    policy = root / "policy.yaml"
    suite_rows = []
    baseline_rows = []
    candidate_rows = []
    for index in range(6):
        case_id = f"case-{index}"
        expected = f"label-{index}"
        rare = index >= 4
        suite_rows.append(
            {
                "case_id": case_id,
                "input": {"index": index},
                "expected": expected,
                "slices": {"frequency": "rare" if rare else "common"},
            }
        )
        baseline_rows.append({"case_id": case_id, "output": expected})
        output = "wrong" if candidate_fails and rare else expected
        candidate_rows.append({"case_id": case_id, "output": output})
    for path, rows in (
        (suite, suite_rows),
        (baseline, baseline_rows),
        (candidate, candidate_rows),
    ):
        path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )
    policy.write_text(
        """schema_version: 1.0.0
policy_id: recorded-release
rules:
  - rule_id: overall-quality
    metric: accuracy
    margin: 1.0
    min_pairs: 6
  - rule_id: rare-quality
    metric: accuracy@frequency=rare
    margin: 0.1
    min_pairs: 2
""",
        encoding="utf-8",
    )
    return baseline, candidate, suite, policy


def test_compare_cli_blocks_and_writes_all_ci_artifacts(tmp_path: Path) -> None:
    baseline, candidate, suite, policy = _write_fixture(tmp_path)
    output = tmp_path / "run"
    github_summary = tmp_path / "step-summary.md"

    result = runner.invoke(
        app,
        [
            "compare",
            str(baseline),
            str(candidate),
            "--suite",
            str(suite),
            "--policy",
            str(policy),
            "--slice-key",
            "frequency",
            "--output",
            str(output),
            "--resamples",
            "200",
        ],
        env={"GITHUB_STEP_SUMMARY": str(github_summary)},
    )

    assert result.exit_code == 2
    assert "EVALUATION DECISION: BLOCK" in result.stdout
    assert {path.name for path in output.iterdir() if path.is_file()} == {
        "evidence-manifest.json",
        "junit.xml",
        "mcr-report.json",
        "release-plan.json",
        "results.sarif",
        "summary.md",
    }
    junit = ElementTree.parse(output / "junit.xml").getroot()
    assert junit.attrib["failures"] == "1"
    sarif = json.loads((output / "results.sarif").read_text("utf-8"))
    assert sarif["runs"][0]["results"][0]["level"] == "error"
    assert "Evaluation decision: BLOCK" in github_summary.read_text("utf-8")


def test_compare_cli_passes_and_returns_zero(tmp_path: Path) -> None:
    baseline, candidate, suite, policy = _write_fixture(tmp_path, candidate_fails=False)
    result = runner.invoke(
        app,
        [
            "compare",
            str(baseline),
            str(candidate),
            "--suite",
            str(suite),
            "--policy",
            str(policy),
            "--slice-key",
            "frequency",
            "--output",
            str(tmp_path / "run"),
            "--resamples",
            "100",
        ],
    )
    assert result.exit_code == 0
    assert "EVALUATION DECISION: PASS" in result.stdout


@pytest.mark.parametrize(("allow_warn", "expected_exit"), [(False, 4), (True, 4)])
def test_compare_cli_warn_is_fail_closed_unless_policy_opts_in(
    tmp_path: Path, allow_warn: bool, expected_exit: int
) -> None:
    baseline, candidate, suite, policy = _write_fixture(tmp_path)
    policy.write_text(
        f"""schema_version: 1.0.0
policy_id: insufficient-release
allow_warn: {str(allow_warn).lower()}
rules:
  - rule_id: overall-quality
    metric: accuracy
    margin: 1.0
    min_pairs: 30
  - rule_id: rare-quality
    metric: accuracy@frequency=rare
    margin: 0.1
    min_pairs: 30
""",
        encoding="utf-8",
    )
    output = tmp_path / "warn-run"
    result = runner.invoke(
        app,
        [
            "compare",
            str(baseline),
            str(candidate),
            "--suite",
            str(suite),
            "--policy",
            str(policy),
            "--slice-key",
            "frequency",
            "--output",
            str(output),
            "--resamples",
            "100",
        ],
    )

    assert result.exit_code == expected_exit
    report = json.loads((output / "mcr-report.json").read_text("utf-8"))
    assert report["decision"]["status"] == "INSUFFICIENT_POWER"
    assert report["decision"]["allowed"] is False
    assert "EVALUATION POLICY SATISFIED: false" in result.stdout
    assert "DEPLOYMENT AUTHORIZATION: NOT EVALUATED" in result.stdout
    junit = ElementTree.parse(output / "junit.xml").getroot()
    assert junit.attrib["failures"] == "2"
    sarif = json.loads((output / "results.sarif").read_text("utf-8"))
    assert {item["level"] for item in sarif["runs"][0]["results"]} == {"error"}


def test_compare_cli_returns_error_for_missing_record(tmp_path: Path) -> None:
    baseline, candidate, suite, policy = _write_fixture(tmp_path)
    rows = candidate.read_text("utf-8").splitlines()
    candidate.write_text("\n".join(rows[:-1]) + "\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "compare",
            str(baseline),
            str(candidate),
            "--suite",
            str(suite),
            "--policy",
            str(policy),
            "--slice-key",
            "frequency",
            "--output",
            str(tmp_path / "run"),
            "--resamples",
            "100",
        ],
    )
    assert result.exit_code == 3
    assert "ERROR:" in result.stderr
    assert "missing" in result.stderr


def test_loaders_reject_duplicates_and_unsafe_yaml(tmp_path: Path) -> None:
    suite = tmp_path / "suite.jsonl"
    row = json.dumps({"case_id": "duplicate", "input": 1, "expected": 1})
    suite.write_text(f"{row}\n{row}\n", encoding="utf-8")
    with pytest.raises(InputFormatError, match="duplicate case_id"):
        load_suite(suite)

    policy = tmp_path / "policy.yaml"
    policy.write_text("!!python/object/apply:os.system ['echo unsafe']\n", encoding="utf-8")
    with pytest.raises(InputFormatError, match="invalid policy YAML"):
        load_policy(policy)


def test_historical_llamacpp_regression_replay_blocks(tmp_path: Path) -> None:
    fixture = Path("examples/historical_llamacpp_22544")
    result = runner.invoke(
        app,
        [
            "compare",
            str(fixture / "baseline.jsonl"),
            str(fixture / "candidate.jsonl"),
            "--suite",
            str(fixture / "suite.jsonl"),
            "--policy",
            str(fixture / "policy.yaml"),
            "--output",
            str(tmp_path / "llamacpp-22544"),
            "--resamples",
            "100",
        ],
    )

    assert result.exit_code == 2
    report = json.loads((tmp_path / "llamacpp-22544" / "mcr-report.json").read_text("utf-8"))
    assert report["decision"]["status"] == "BLOCK"
    assert len(report["decision"]["findings"]) == 3
