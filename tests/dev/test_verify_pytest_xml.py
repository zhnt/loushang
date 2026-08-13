from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_verifier_accepts_nonempty_passing_report_and_required_property(
    tmp_path: Path,
) -> None:
    result = _run_verifier(
        tmp_path,
        '<testsuites><testsuite tests="2" skipped="0" failures="0" errors="0">'
        '<properties><property name="terminal_backend" value="conpty"/>'
        "</properties></testsuite></testsuites>",
        "--require-property",
        "terminal_backend=conpty",
    )

    assert result.returncode == 0
    assert "tests=2" in result.stdout


def test_verifier_rejects_empty_report(tmp_path: Path) -> None:
    result = _run_verifier(
        tmp_path,
        '<testsuites><testsuite tests="0" skipped="0" failures="0" errors="0"/>'
        "</testsuites>",
    )

    assert result.returncode == 1
    assert "tests must be greater than zero" in result.stderr


def test_verifier_rejects_skipped_failed_or_error_results(tmp_path: Path) -> None:
    result = _run_verifier(
        tmp_path,
        '<testsuites><testsuite tests="4" skipped="1" failures="1" errors="1"/>'
        "</testsuites>",
    )

    assert result.returncode == 1
    assert "skipped must be zero" in result.stderr
    assert "failures must be zero" in result.stderr
    assert "errors must be zero" in result.stderr


def test_verifier_rejects_wrong_required_property(tmp_path: Path) -> None:
    result = _run_verifier(
        tmp_path,
        '<testsuites><testsuite tests="1" skipped="0" failures="0" errors="0">'
        '<properties><property name="terminal_backend" value="posix-pty"/>'
        "</properties></testsuite></testsuites>",
        "--require-property",
        "terminal_backend=conpty",
    )

    assert result.returncode == 1
    assert "terminal_backend" in result.stderr


def _run_verifier(
    tmp_path: Path, xml: str, *args: str
) -> subprocess.CompletedProcess[str]:
    report = tmp_path / "pytest.xml"
    report.write_text(xml, encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            "scripts/dev/verify_pytest_xml.py",
            str(report),
            *args,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
