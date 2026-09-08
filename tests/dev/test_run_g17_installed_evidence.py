from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from .test_run_g16_installed_evidence import _source_wheel

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts/dev/run_g17_installed_evidence.py"
_SPEC = importlib.util.spec_from_file_location("run_g17_installed_evidence", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
runner = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(runner)


def test_g17_partial_wheel_smoke_cannot_write_or_verify_release_report(tmp_path, monkeypatch):
    wheel = _source_wheel(tmp_path)
    calls, reports = [], []
    monkeypatch.setattr(runner, "_ROOT", tmp_path)
    monkeypatch.setattr(runner.shutil, "which", lambda _: "/fake/uv")
    monkeypatch.setattr(runner, "_run", lambda argv, **kwargs: calls.append((argv, kwargs)))
    monkeypatch.setattr(runner, "_verify_smoke", reports.append)
    assert runner.main(["--wheel", str(wheel), "--platform", sys.platform, "--smoke"]) == 0
    assert reports == [tmp_path / f".artifacts/g17-wheel-smoke-{sys.platform}.xml"]
    command = next(argv for argv, _ in calls if "pytest" in argv)
    assert "-I" in command and "-k" in command
    assert "--g17-installed-evidence" not in command
    assert f"pythonpath={tmp_path}" in command
    assert str(tmp_path / "tests/coding/test_hosted_workflow_terminal.py") in command
    assert not any("verify_evidence_manifest.py" in arg for argv, _ in calls for arg in argv)
    probe = next(argv for argv, _ in calls if "-c" in argv)
    assert "loushang.coding.cli.hosted_client" in probe[probe.index("-c") + 1]
    assert "loushang.apphost.launcher" in probe[probe.index("-c") + 1]
    assert "loushang.coding.cli.__main__" in probe[probe.index("-c") + 1]
    assert "loushang.coding.ui.mode" in probe[probe.index("-c") + 1]
    for _, options in calls:
        assert not {"pythonpath", "pythonhome", "virtual_env"} & {
            key.lower() for key in options["environment"]
        }


def test_g17_release_refuses_missing_complete_selector_before_installation(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "_ROOT", tmp_path)
    monkeypatch.setattr(runner, "_run", lambda *_, **__: pytest.fail("unexpected installation"))
    with pytest.raises(SystemExit) as error:
        runner.main(["--wheel", str(tmp_path / "absent.whl"), "--platform", sys.platform])
    assert error.value.code == 2


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_g17_full_refuses_uncomposed_platform_before_installation(tmp_path, monkeypatch, platform):
    selector = tmp_path / "tests/coding/test_hosted_installed_evidence.py"
    selector.parent.mkdir(parents=True)
    selector.touch()
    monkeypatch.setattr(runner, "_ROOT", tmp_path)
    monkeypatch.setattr(runner.sys, "platform", platform)
    monkeypatch.setattr(runner, "_run", lambda *_, **__: pytest.fail("unexpected installation"))
    with pytest.raises(SystemExit) as error:
        runner.main(["--wheel", str(tmp_path / "absent.whl"), "--platform", platform])
    assert error.value.code == 2


def test_g17_full_uses_only_complete_selector_and_release_verifier(tmp_path, monkeypatch):
    wheel = _source_wheel(tmp_path)
    selector = tmp_path / "tests/coding/test_hosted_installed_evidence.py"
    selector.parent.mkdir(parents=True)
    selector.touch()
    calls = []
    monkeypatch.setattr(runner, "_ROOT", tmp_path)
    monkeypatch.setattr(runner.sys, "platform", "linux")
    monkeypatch.setattr(runner.shutil, "which", lambda _: "/fake/uv")
    monkeypatch.setattr(runner, "_run", lambda argv, **kwargs: calls.append(argv))
    monkeypatch.setattr(runner, "_verify_smoke", lambda _: pytest.fail("unexpected smoke"))
    assert runner.main(["--wheel", str(wheel), "--platform", "linux"]) == 0
    command, = [argv for argv in calls if "pytest" in argv]
    assert str(selector) in command and "-k" not in command
    assert "--g17-installed-evidence" in command
    assert f"--junitxml={tmp_path / '.artifacts/g17-wheel-linux.xml'}" in command
    verification, = [argv for argv in calls if any("verify_evidence_manifest.py" in item for item in argv)]
    assert verification[-2:] == ["G17-WHEEL-LINUX", ".artifacts/g17-wheel-linux.xml"]


@pytest.mark.parametrize("enabled", [False, True])
def test_g17_wheel_selector_needs_explicit_collection_activation(enabled):
    root = _SCRIPT.parents[2]
    command = [
        sys.executable, "-I", "-m", "pytest", "-c", str(root / "pyproject.toml"),
        "-o", f"pythonpath={root}", "--collect-only", "-q",
        str(root / "tests/coding/test_hosted_installed_evidence.py"),
    ]
    if enabled:
        command.append("--g17-installed-evidence")
    result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=45)
    assert result.returncode == (0 if enabled else 5), result.stdout + result.stderr
    cases = [line for line in result.stdout.splitlines() if "::test_G17_installed_evidence[" in line]
    assert len(cases) == (8 if enabled else 0), result.stdout
    if not enabled:
        assert "(8 deselected)" in result.stdout


@pytest.mark.parametrize("fault", [None, "missing", "duplicate", "unexpected", "skipped", "failure", "error"])
def test_g17_smoke_requires_exact_cases_without_skip(tmp_path, fault):
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite")
    names = sorted(runner._SMOKE_NAMES)
    if fault == "missing":
        names.pop()
    elif fault == "duplicate":
        names[-1] = names[0]
    elif fault == "unexpected":
        names[-1] = "unrelated_success"
    for name in names:
        case = ET.SubElement(suite, "testcase", name=name)
    if fault in {"skipped", "failure", "error"}:
        ET.SubElement(case, fault)
    report = tmp_path / "smoke.xml"
    ET.ElementTree(root).write(report)
    if fault is None:
        runner._verify_smoke(report)
    else:
        with pytest.raises(ValueError):
            runner._verify_smoke(report)


def test_g17_smoke_checks_survive_optimized_outer_interpreter(tmp_path):
    report = tmp_path / "empty.xml"
    report.write_text("<testsuites><testsuite /></testsuites>")
    result = subprocess.run(
        [sys.executable, "-I", "-O", "-c",
         "import runpy,sys; from pathlib import Path; "
         "runpy.run_path(sys.argv[1])['_verify_smoke'](Path(sys.argv[2]))",
         str(_SCRIPT), str(report)],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode != 0
    assert "ValueError: G17 smoke needs exactly five selected cases" in result.stderr


@pytest.mark.parametrize("fail", [False, True])
def test_g17_workspace_retains_failed_inputs_but_removes_successful_installation(tmp_path, fail):
    root = None
    try:
        with runner._workspace(tmp_path) as root:
            (root / "failure-input").write_text("evidence")
            if fail:
                raise ValueError("failed test")
    except ValueError:
        assert fail
    assert root is not None and root.exists() is fail


@pytest.mark.skipif(os.name != "posix", reason="POSIX immutable snapshot permissions")
def test_g17_workspace_removes_readonly_directories_without_chmod_hardlinked_files(tmp_path):
    outside = tmp_path / "cached-source"
    outside.write_text("must remain readonly")
    outside.chmod(0o400)
    with runner._workspace(tmp_path) as root:
        snapshot = root / "snapshot"
        snapshot.mkdir()
        os.link(outside, snapshot / "standard.md")
        (root / "external-link").symlink_to(outside)
        snapshot.chmod(0o500)
    assert not root.exists()
    assert outside.read_text() == "must remain readonly"
    assert stat.S_IMODE(outside.stat().st_mode) == 0o400
