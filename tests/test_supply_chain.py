from __future__ import annotations

import re
import shutil
import subprocess
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
    pypi_state = workflow["jobs"]["pypi-state"]
    assert pypi_state["needs"] == ["build", "attest"]
    assert pypi_state["permissions"] == {"contents": "read"}
    assert "id-token" not in pypi_state["permissions"]
    publish = workflow["jobs"]["publish"]
    assert publish["needs"] == ["build", "attest", "pypi-state"]
    assert publish["permissions"] == {"contents": "read", "id-token": "write"}
    assert publish["environment"]["name"] == "pypi"
    assert "MERRIV_BRAND_CLEARED" in publish["if"]
    assert "pypa/gh-action-pypi-publish@" in source
    assert "verify_pypi_release.py" in source
    assert "needs.pypi-state.outputs.state == 'absent'" in publish["if"]
    assert "--require-existing" in source
    assert "skip-existing" not in source
    assert "actions/checkout@" not in str(publish)
    pypi_confirm = workflow["jobs"]["pypi-confirm"]
    assert pypi_confirm["permissions"] == {"contents": "read"}
    assert "id-token" not in pypi_confirm["permissions"]
    assert "needs.publish.result == 'skipped'" in pypi_confirm["if"]
    github_release = workflow["jobs"]["github-release"]
    assert github_release["needs"] == ["build", "attest", "pypi-confirm"]
    assert github_release["permissions"] == {"contents": "write"}
    assert "needs.pypi-confirm.result == 'success'" in github_release["if"]
    assert "gh release create" in source
    assert "gh release upload" in source
    assert "--clobber" in source
    assert "dist/*" in source
    assert "--prerelease" in source
    assert "secrets." not in source


def test_ci_installs_the_frozen_lock_before_audit() -> None:
    source = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")

    audit_index = source.index("python -m pip_audit --local --skip-editable")
    sync_command = "uv sync --frozen --extra dev --extra onnx"
    assert "astral-sh/setup-uv@" in source
    assert 'version: "0.11.18"' in source
    assert sync_command in source
    assert source.index(sync_command) < audit_index

    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    pip_match = re.search(r'name = "pip"\nversion = "(\d+)\.(\d+)\.', lock)
    assert pip_match is not None
    assert tuple(map(int, pip_match.groups())) >= (26, 2)

    setuptools_match = re.search(r'name = "setuptools"\nversion = "(\d+)\.(\d+)\.', lock)
    if setuptools_match is not None:
        assert tuple(map(int, setuptools_match.groups())) >= (83, 0)


def test_reproducible_build_outputs_stay_outside_the_source_tree() -> None:
    source = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")

    assert '${RUNNER_TEMP}/merriv-repro-' in source
    assert "python -m build --outdir dist-a" not in source


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
    assert "merriv mcr verify" in source
    assert (
        names.index("Verify portable report identities")
        < names.index("Resolve final action result")
        < names.index("Upload release evidence")
        < names.index("Enforce release decision")
    )
    assert action["outputs"]["exit-code"]["value"] == "${{ steps.final.outputs.exit-code }}"
    assert "MERRIV_VERIFY_EXIT_CODE" in source
    assert "final_code=3" in source
    assert "--require-hashes" in source
    assert "--no-deps" in source
    assert "--no-build-isolation" in source
    dependency_lock = (ROOT / "action-requirements.lock").read_text("utf-8")
    assert "--hash=sha256:" in dependency_lock
    assert "hatchling==1.32.0" in dependency_lock
    assert "${{ inputs.baseline }}" not in next(
        step["run"] for step in steps if step["name"] == "Compare and gate candidate"
    )


def test_ci_executes_the_local_composite_action_and_checks_its_outputs() -> None:
    source = (WORKFLOWS / "ci.yml").read_text("utf-8")
    assert "uses: ./" in source
    assert "steps.gate.outputs.exit-code" in source
    assert 'test "$MERRIV_ACTION_EXIT_CODE" = "0"' in source
    assert "merriv mcr verify runs/action-smoke" in source


def test_release_fails_early_when_tag_and_package_version_differ() -> None:
    source = (WORKFLOWS / "release.yml").read_text("utf-8")

    assert "Verify release tag matches package version" in source
    assert 'expected_tag="v${package_version}"' in source
    assert '"${GITHUB_REF_NAME}" != "${expected_tag}"' in source


def test_release_build_backend_is_exact_and_preinstalled() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")

    assert 'requires = ["hatchling==1.32.0"]' in pyproject
    assert "--group action-build" in release
    assert "python -m build --no-isolation" in release
    assert "python -m build --no-isolation" in ci


def test_merriv_is_the_distribution_module_and_only_cli() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'name = "merriv"' in pyproject
    assert 'merriv = "merriv.cli:app"' in pyproject
    assert 'packages = ["src/merriv"]' in pyproject
    assert 'packages = ["merriv"]' in pyproject


def test_retired_brand_is_absent_from_tracked_paths_and_content() -> None:
    retired = b"m2" + b"riv"
    git = shutil.which("git")
    assert git is not None
    tracked = subprocess.run(
        [git, "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.split(b"\0")

    for encoded_path in filter(None, tracked):
        assert retired not in encoded_path.lower(), encoded_path
        path = ROOT / encoded_path.decode("utf-8")
        assert retired not in path.read_bytes().lower(), path


def test_nvidia_runner_uses_isolated_cache_and_hash_locked_dependencies() -> None:
    source = (WORKFLOWS / "nvidia-vertical.yml").read_text(encoding="utf-8")

    assert "astral-sh/setup-uv@" in source
    assert 'version: "0.11.18"' in source
    assert "enable-cache: false" in source
    assert "UV_CACHE_DIR: .uv-cache-${{ github.run_id }}" in source
    assert "uv sync --frozen --extra onnx-demo" in source
    assert source.count("--require-hashes") == 2
    assert "python -m pip" not in source

    for name in (
        "requirements-modelopt.lock",
        "requirements-tensorrt-cu125-windows.lock",
    ):
        lock = (ROOT / "examples" / "nvidia_tensorrt_vertical" / name).read_text("utf-8")
        package_blocks = [
            block for block in re.split(r"(?m)(?=^[A-Za-z0-9])", lock) if "==" in block
        ]
        assert package_blocks
        assert all("--hash=sha256:" in block for block in package_blocks)
