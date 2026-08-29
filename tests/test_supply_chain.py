from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
WORKFLOW_FILES = (
    tuple(WORKFLOWS.glob("*.yml")) + tuple(ROOT.glob("examples/**/*.yml")) + (ROOT / "action.yml",)
)
IMMUTABLE_ACTION = re.compile(r"^\s*uses:\s+[^\s@]+@[0-9a-f]{40}(?:\s+#.*)?$")


def test_every_external_action_is_pinned_to_a_commit() -> None:
    uses_lines = [
        line
        for workflow in WORKFLOW_FILES
        for line in workflow.read_text("utf-8").splitlines()
        if line.strip().startswith("uses:")
    ]
    assert uses_lines
    external_uses = [line for line in uses_lines if not line.strip().startswith("uses: ./")]
    assert external_uses
    assert all(IMMUTABLE_ACTION.match(line) for line in external_uses)


def test_release_build_has_provenance_sbom_and_gated_trusted_publish() -> None:
    source = (WORKFLOWS / "release.yml").read_text("utf-8")
    workflow = yaml.load(source, Loader=yaml.BaseLoader)
    build = workflow["jobs"]["build"]

    assert "permissions" not in build
    attest = workflow["jobs"]["attest"]
    assert attest["needs"] == "build"
    assert attest["permissions"] == {
        "attestations": "write",
        "contents": "read",
        "id-token": "write",
    }
    assert "actions/attest@" in source
    assert "anchore/sbom-action@" in source
    assert "SHA256SUMS" in source
    assert "packages: write" not in source
    publish = workflow["jobs"]["publish"]
    assert publish["needs"] == ["build", "attest"]
    assert publish["permissions"] == {"contents": "read", "id-token": "write"}
    assert publish["environment"]["name"] == "pypi"
    assert "M2RIV_BRAND_CLEARED" in publish["if"]
    assert "pypa/gh-action-pypi-publish@" in source
    assert "secrets." not in source


def test_ci_upgrades_vulnerable_packaging_bootstrap_before_audit() -> None:
    source = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")

    assert 'python -m pip install "setuptools>=83"' in source
    assert source.index('python -m pip install "setuptools>=83"') < source.index(
        "python -m pip_audit --local --skip-editable"
    )


def test_checkout_never_persists_credentials() -> None:
    for workflow in WORKFLOW_FILES:
        source = workflow.read_text("utf-8")
        checkout_count = source.count("uses: actions/checkout@")
        assert source.count("persist-credentials: false") == checkout_count


def test_reusable_action_verifies_and_uploads_before_enforcing_decision() -> None:
    source = (ROOT / "action.yml").read_text("utf-8")
    action = yaml.load(source, Loader=yaml.BaseLoader)
    steps = action["runs"]["steps"]
    names = [step["name"] for step in steps]

    assert action["runs"]["using"] == "composite"
    assert "m2riv mcr verify" in source
    assert (
        names.index("Verify portable report identities")
        < names.index("Resolve final action result")
        < names.index("Upload release evidence")
        < names.index("Enforce release decision")
    )
    assert action["outputs"]["exit-code"]["value"] == "${{ steps.final.outputs.exit-code }}"
    assert "M2RIV_VERIFY_EXIT_CODE" in source
    assert "final_code=3" in source
    assert "--require-hashes" in source
    assert "--no-deps" in source
    dependency_lock = (ROOT / "action-requirements.lock").read_text("utf-8")
    assert "--hash=sha256:" in dependency_lock
    assert "${{ inputs.baseline }}" not in next(
        step["run"] for step in steps if step["name"] == "Compare and gate candidate"
    )


def test_ci_executes_the_local_composite_action_and_checks_its_outputs() -> None:
    source = (WORKFLOWS / "ci.yml").read_text("utf-8")
    assert "uses: ./" in source
    assert "steps.gate.outputs.exit-code" in source
    assert 'test "$M2RIV_ACTION_EXIT_CODE" = "2"' in source
    assert "m2riv mcr verify runs/action-smoke" in source
