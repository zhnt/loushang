from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts/dev/verify_evidence_manifest.py"
SPEC = importlib.util.spec_from_file_location("verify_evidence_manifest", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
verify_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verify_module
SPEC.loader.exec_module(verify_module)
verify_manifest_report = verify_module.verify_manifest_report


def _write_manifest(path: Path, report: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "manifestVersion": 1,
                "reports": {
                    "G8": {
                        "junitPath": report.as_posix(),
                        "minimumTests": 2,
                        "requiredCaseIds": ["G8-ONE", "G8-TWO"],
                        "status": "implemented",
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def _write_report(path: Path, *, second: str = "G8-TWO", skipped: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '<testsuite errors="0" failures="0" skipped="%d" tests="2">'
        '<testcase name="test_one[G8-ONE]" />'
        '<testcase name="test_two[%s]">%s</testcase>'
        "</testsuite>"
        % (int(skipped), second, "<skipped />" if skipped else ""),
        encoding="utf-8",
    )


def test_generic_evidence_manifest_accepts_exact_zero_skip_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    manifest = Path("manifest.json")
    report = Path(".artifacts/g8.xml")
    _write_manifest(manifest, report)
    _write_report(report)

    assert verify_manifest_report(manifest, "G8", report) == (
        "tests=2, skipped=0, failures=0, errors=0"
    )


@pytest.mark.parametrize(
    ("second", "skipped"),
    (("G8-OTHER", False), ("G8-TWO", True), ("G8-ONE", False)),
)
def test_generic_evidence_manifest_rejects_missing_skipped_or_duplicate_cases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    second: str,
    skipped: bool,
) -> None:
    monkeypatch.chdir(tmp_path)
    manifest = Path("manifest.json")
    report = Path(".artifacts/g8.xml")
    _write_manifest(manifest, report)
    _write_report(report, second=second, skipped=skipped)

    with pytest.raises(ValueError):
        verify_manifest_report(manifest, "G8", report)
