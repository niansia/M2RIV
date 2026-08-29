from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
WORKFLOW_FILES = tuple(WORKFLOWS.glob("*.yml")) + tuple(
    ROOT.glob("examples/**/*.yml")
) + (ROOT / "action.yml",)
IMMUTABLE_ACTION = re.compile(r"^\s*uses:\s+[^\s@]+@[0-9a-f]{40}(?:\s+#.*)?$")


def test_every_external_action_is_pinned_to_a_commit() -> None:
    uses_lines = [
        line
        for workflow in WORKFLOW_FILES
        for line in workflow.read_text("utf-8").splitlines()
        if line.strip().startswith("uses:")
    ]
    assert uses_lines
    assert all(IMMUTABLE_ACTION.match(line) for line in uses_lines)


def test_release_build_has_provenance_sbom_and_gated_trusted_publish() -> None:
    source = (WORKFLOWS / "release.yml").read_text("utf-8")
    workflow = yaml.load(source, Loader=yaml.BaseLoader)
    build = workflow["jobs"]["build"]

    assert build["permissions"] == {
        "attestations": "write",
        "contents": "read",
        "id-token": "write",
    }
    assert "actions/attest@" in source
    assert "anchore/sbom-action@" in source
    assert "SHA256SUMS" in source
    assert "packages: write" not in source
    publish = workflow["jobs"]["publish"]
    assert publish["needs"] == "build"
    assert publish["permissions"] == {"contents": "read", "id-token": "write"}
    assert publish["environment"]["name"] == "pypi"
    assert "M2RIV_BRAND_CLEARED" in publish["if"]
    assert "pypa/gh-action-pypi-publish@" in source
    assert "secrets." not in source


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
    assert names.index("Verify portable report identities") < names.index(
        "Upload release evidence"
    ) < names.index("Enforce release decision")
    assert "${{ inputs.baseline }}" not in next(
        step["run"] for step in steps if step["name"] == "Compare and gate candidate"
    )
