from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts/dev/verify_plc9c5_manifest.py"
SPEC = importlib.util.spec_from_file_location("verify_plc9c5_manifest", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
verify_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verify_module
SPEC.loader.exec_module(verify_module)
verify_manifest_report = verify_module.verify_manifest_report


def _write_manifest(path: Path, *, status: str = "implemented") -> None:
    path.write_text(
        json.dumps(
            {
                "manifestVersion": 1,
                "reports": {
                    "PLC9C5-C5.1-CONTRACT": {
                        "junitPath": ".artifacts/plc9c5-c51-contract.xml",
                        "minimumTests": 2,
                        "requiredCaseIds": ["C51-ONE", "C51-TWO"],
                        "status": status,
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def _write_report(
    path: Path,
    *,
    second_case: str = "C51-TWO",
    skipped: int = 0,
    failures: int = 0,
    errors: int = 0,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    first_result = "<failure />" if failures else ("<error />" if errors else "")
    second_result = "<skipped />" if skipped else ""
    path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuite errors="%d" failures="%d" skipped="%d" tests="2">
  <testcase classname="contract" name="test_case[C51-ONE]">%s</testcase>
  <testcase classname="contract" name="test_case[%s]">%s</testcase>
</testsuite>
"""
        % (errors, failures, skipped, first_result, second_case, second_result),
        encoding="utf-8",
    )


def test_verify_plc9c5_manifest_accepts_exact_required_case_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    manifest = Path("manifest.json")
    report = Path(".artifacts/plc9c5-c51-contract.xml")
    _write_manifest(manifest)
    _write_report(report)

    assert verify_manifest_report(manifest, "PLC9C5-C5.1-CONTRACT", report) == (
        "tests=2, skipped=0, failures=0, errors=0"
    )


def test_verify_plc9c5_manifest_rejects_substituted_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    manifest = Path("manifest.json")
    report = Path(".artifacts/plc9c5-c51-contract.xml")
    _write_manifest(manifest)
    _write_report(report, second_case="C51-OTHER")

    with pytest.raises(ValueError, match="case ids mismatch"):
        verify_manifest_report(manifest, "PLC9C5-C5.1-CONTRACT", report)


def test_verify_plc9c5_manifest_rejects_duplicate_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    manifest = Path("manifest.json")
    report = Path(".artifacts/plc9c5-c51-contract.xml")
    _write_manifest(manifest)
    _write_report(report, second_case="C51-ONE")

    with pytest.raises(ValueError, match="duplicates=1"):
        verify_manifest_report(manifest, "PLC9C5-C5.1-CONTRACT", report)


@pytest.mark.parametrize(
    ("skipped", "failures", "errors"),
    ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
)
def test_verify_plc9c5_manifest_rejects_skipped_or_failing_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    skipped: int,
    failures: int,
    errors: int,
) -> None:
    monkeypatch.chdir(tmp_path)
    manifest = Path("manifest.json")
    report = Path(".artifacts/plc9c5-c51-contract.xml")
    _write_manifest(manifest)
    _write_report(report, skipped=skipped, failures=failures, errors=errors)

    with pytest.raises(ValueError, match="must be zero"):
        verify_manifest_report(manifest, "PLC9C5-C5.1-CONTRACT", report)


def test_verify_plc9c5_manifest_rejects_planned_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    manifest = Path("manifest.json")
    report = Path(".artifacts/plc9c5-c51-contract.xml")
    _write_manifest(manifest, status="planned")
    _write_report(report)

    with pytest.raises(ValueError, match="not implemented"):
        verify_manifest_report(manifest, "PLC9C5-C5.1-CONTRACT", report)


@pytest.mark.parametrize(
    ("report_xml", "message"),
    (
        (
            '<testsuite errors="0" failures="0" skipped="0" tests="2">'
            '<testcase name="test[C51-ONE]"><failure /></testcase>'
            '<testcase name="test[C51-TWO]" /></testsuite>',
            "counts do not match",
        ),
        (
            '<testsuite errors="0" failures="0" skipped="0" tests="-2">'
            '<testcase name="test[C51-ONE]" />'
            '<testcase name="test[C51-TWO]" /></testsuite>',
            "negative",
        ),
        (
            '<testsuite errors="0" failures="0" tests="2">'
            '<testcase name="test[C51-ONE]" />'
            '<testcase name="test[C51-TWO]" /></testsuite>',
            "missing",
        ),
        (
            '<testsuite errors="0" failures="0" skipped="0" tests="2">'
            '<testsuite errors="0" failures="0" skipped="0" tests="2">'
            '<testcase name="test[C51-ONE]" />'
            '<testcase name="test[C51-TWO]" /></testsuite></testsuite>',
            "nested",
        ),
        (
            '<testsuites tests="3" skipped="0" failures="0" errors="0">'
            '<testsuite errors="0" failures="0" skipped="0" tests="2">'
            '<testcase name="test[C51-ONE]" />'
            '<testcase name="test[C51-TWO]" /></testsuite></testsuites>',
            "aggregate counts",
        ),
    ),
)
def test_verify_plc9c5_manifest_rejects_untrusted_junit_aggregates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    report_xml: str,
    message: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    manifest = Path("manifest.json")
    report = Path(".artifacts/plc9c5-c51-contract.xml")
    _write_manifest(manifest)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(report_xml, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        verify_manifest_report(manifest, "PLC9C5-C5.1-CONTRACT", report)
