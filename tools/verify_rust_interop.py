"""Exercise positive and adversarial Python/Rust MCR interoperability."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from merriv.reports import MCRVerificationError, verify_report_bundle

ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "reference" / "mcr-reference-rust" / "Cargo.toml"
SIMPLE_EVIDENCE = ROOT / "reference" / "mcr-reference-rust" / "simple-evidence.json"
PYTHON_BUNDLE = ROOT / "examples" / "mcr_conformance" / "full"


def _cargo(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    cargo = shutil.which("cargo")
    if cargo is None:
        raise RuntimeError("cargo is required for Rust interoperability verification")
    return subprocess.run(  # noqa: S603 - resolved executable and fixed argument structure
        [cargo, "run", "--locked", "--quiet", "--manifest-path", str(MANIFEST), "--", *arguments],
        check=check,
        capture_output=True,
        text=True,
        timeout=180,
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="merriv-rust-interop-") as temporary:
        bundle = Path(temporary) / "rust-bundle"
        _cargo("produce", str(SIMPLE_EVIDENCE), str(bundle))
        python_result = verify_report_bundle(bundle, require_complete=True)
        if not python_result.integrity_valid or not python_result.bundle_verification_complete:
            raise RuntimeError("Python did not completely verify the Rust-produced MCR")
        _cargo("verify", str(bundle))

        report_path = bundle / "mcr-report.json"
        original = json.loads(report_path.read_text(encoding="utf-8"))

        utc_z = original | {"created_at": original["created_at"].replace("+00:00", "Z")}
        report_path.write_text(json.dumps(utc_z, indent=2) + "\n", encoding="utf-8")
        verify_report_bundle(bundle, require_complete=True)
        _cargo("verify", str(bundle))

        tampered = original.copy()
        tampered["metrics"] = [item.copy() for item in original["metrics"]]
        tampered["metrics"][0]["candidate_value"] = 0.1
        report_path.write_text(json.dumps(tampered, indent=2) + "\n", encoding="utf-8")
        try:
            verify_report_bundle(bundle, require_complete=True)
        except MCRVerificationError:
            pass
        else:
            raise RuntimeError("Python accepted a tampered Rust-produced MCR")
        rust_tamper = _cargo("verify", str(bundle), check=False)
        if rust_tamper.returncode == 0:
            raise RuntimeError("Rust accepted a tampered MCR")

    _cargo("verify", str(PYTHON_BUNDLE))
    print("Python/Rust MCR interop verified, including UTC equivalence and tamper rejection")


if __name__ == "__main__":
    main()
