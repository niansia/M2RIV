from pathlib import Path

from typer.testing import CliRunner

from m2riv.cli import app
from m2riv.core.models import ModelSnapshot

runner = CliRunner()


def test_inspect_outputs_valid_snapshot(tmp_path: Path) -> None:
    artifact = tmp_path / "model.bin"
    artifact.write_bytes(b"weights")

    result = runner.invoke(app, ["inspect", str(artifact), "--family", "cv"])

    assert result.exit_code == 0
    snapshot = ModelSnapshot.model_validate_json(result.stdout)
    assert snapshot.model_family.value == "cv"


def test_schema_export(tmp_path: Path) -> None:
    destination = tmp_path / "schemas"
    result = runner.invoke(app, ["schema", "export", str(destination)])

    assert result.exit_code == 0
    generated = sorted(destination.glob("*.schema.json"))
    assert len(generated) == 20
    assert any(path.name == "ModelSnapshot.schema.json" for path in generated)
    assert any(path.name == "CompiledReleasePlan.schema.json" for path in generated)
    assert any(path.name == "PluginManifest.schema.json" for path in generated)
    assert any(path.name == "ArtifactProfile.schema.json" for path in generated)
    assert any(path.name == "ArtifactDiff.schema.json" for path in generated)
    assert any(path.name == "EvidenceManifest.schema.json" for path in generated)
