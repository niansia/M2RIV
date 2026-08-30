from __future__ import annotations

from pathlib import Path

from merriv.adapters import AdapterCapability, FakeAdapter, ModelAdapter
from merriv.core.identity import build_local_snapshot
from merriv.core.models import EvalCase, RuntimeProfile


def test_fake_adapter_satisfies_runtime_contract(tmp_path: Path) -> None:
    artifact = tmp_path / "model.bin"
    artifact.write_bytes(b"weights")
    adapter = FakeAdapter(
        snapshot=build_local_snapshot(artifact),
        responses={"known": {"label": "candidate"}},
    )

    assert isinstance(adapter, ModelAdapter)
    assert adapter.capabilities() == frozenset({AdapterCapability.BATCH})


def test_fake_adapter_is_ordered_and_deterministic(tmp_path: Path) -> None:
    artifact = tmp_path / "model.bin"
    artifact.write_bytes(b"weights")
    adapter = FakeAdapter(
        snapshot=build_local_snapshot(artifact),
        responses={"known": {"label": "candidate"}},
    )
    cases = (
        EvalCase(case_id="known", input="ignored"),
        EvalCase(case_id="echo", input={"value": 7}),
    )
    profile = RuntimeProfile(seed=42)

    first = adapter.run(cases, profile)
    second = adapter.run(cases, profile)

    assert [item.case_id for item in first] == ["known", "echo"]
    assert first[0].output == {"label": "candidate"}
    assert first[1].output == {"value": 7}
    assert [item.id for item in first] == [item.id for item in second]
    assert [item.output_digest for item in first] == [item.output_digest for item in second]
