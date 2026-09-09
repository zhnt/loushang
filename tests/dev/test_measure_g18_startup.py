from __future__ import annotations

import base64
import csv
import hashlib
import importlib.util
import json
import os
import sys
from importlib.metadata import PathDistribution
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/dev/measure_g18_startup.py"
SPEC = importlib.util.spec_from_file_location("measure_g18_startup", SCRIPT)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def _wrapper_install(root):
    prefix = root / "install"
    scripts = prefix / "bin"
    metadata = prefix / "lib/python3.11/site-packages/loushang-0.1.0.dist-info"
    scripts.mkdir(parents=True)
    metadata.mkdir(parents=True)
    (metadata / "entry_points.txt").write_text(
        "[console_scripts]\nloushang = loushang.coding.cli.__main__:main\n"
    )
    wrapper = scripts / "loushang"
    wrapper.write_text(
        f"#!{prefix / 'bin/python'}\n"
        "# -*- coding: utf-8 -*-\nimport sys\n"
        "from loushang.coding.cli.__main__ import main\n"
        'if __name__ == "__main__":\n'
        '    if sys.argv[0].endswith("-script.pyw"):\n'
        "        sys.argv[0] = sys.argv[0][:-11]\n"
        '    elif sys.argv[0].endswith(".exe"):\n'
        "        sys.argv[0] = sys.argv[0][:-4]\n"
        "    sys.exit(main())\n"
    )
    wrapper.chmod(0o755)
    _record_wrapper(metadata, wrapper)
    return prefix, metadata, wrapper


def _record_wrapper(metadata, wrapper):
    content = wrapper.read_bytes()
    digest = (
        base64.urlsafe_b64encode(hashlib.sha256(content).digest()).decode().rstrip("=")
    )
    with (metadata / "RECORD").open("w", newline="") as stream:
        csv.writer(stream).writerow(
            ("../../../bin/loushang", f"sha256={digest}", len(content))
        )


@pytest.mark.skipif(sys.platform != "linux", reason="Linux uv wrapper contract")
def test_wrapper_identity_binds_record_target_and_interpreter(tmp_path):
    prefix, metadata, wrapper = _wrapper_install(tmp_path)
    result = runner.verify_console_wrappers(PathDistribution(metadata), prefix)
    assert result == {
        "loushang": {
            "sha256": hashlib.sha256(wrapper.read_bytes()).hexdigest(),
            "target": "loushang.coding.cli.__main__:main",
        }
    }


@pytest.mark.parametrize(
    "tamper",
    [
        "bytes",
        "shebang",
        "target",
        "stub",
        "symlink",
        "directory-symlink",
        "mode",
        "record",
    ],
)
@pytest.mark.skipif(sys.platform != "linux", reason="Linux uv wrapper contract")
def test_wrapper_tampering_is_rejected_even_with_updated_record(tmp_path, tamper):
    prefix, metadata, wrapper = _wrapper_install(tmp_path)
    if tamper == "bytes":
        wrapper.write_text(wrapper.read_text() + "# changed\n")
    elif tamper in {"shebang", "target", "stub"}:
        text = wrapper.read_text()
        if tamper == "shebang":
            text = text.replace(str(prefix / "bin/python"), "/other-venv/bin/python")
        elif tamper == "target":
            text = text.replace("from loushang.coding.cli.__main__", "from unrelated")
        else:
            text = text.replace(
                "sys.exit(main())", "print('usage: loushang --help --model')"
            )
        wrapper.write_text(text)
        _record_wrapper(metadata, wrapper)
    elif tamper == "symlink":
        external = tmp_path / "external"
        wrapper.rename(external)
        wrapper.symlink_to(external)
    elif tamper == "directory-symlink":
        external = tmp_path / "external-bin"
        (prefix / "bin").rename(external)
        (prefix / "bin").symlink_to(external, target_is_directory=True)
    elif tamper == "mode":
        wrapper.chmod(0o600)
    else:
        (metadata / "RECORD").write_text("")
    with pytest.raises(ValueError, match="console wrapper"):
        runner.verify_console_wrappers(PathDistribution(metadata), prefix)


def test_private_environment_rejects_ambient_home_credentials_and_source(
    tmp_path, monkeypatch
):
    values = {
        "HOME": "/poison",
        "OPENAI_API_KEY": "poison",
        "PYTHONPATH": "/poison",
        "LOUSHANG_HOME": "/poison",
        "GIT_CONFIG_COUNT": "1",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    environment = runner.private_environment(
        tmp_path, Path("/private/venv"), tmp_path / "pyc"
    )
    assert environment["HOME"] == str(tmp_path / "home")
    assert environment["LOUSHANG_HOME"] == str(tmp_path / "data")
    assert not {"OPENAI_API_KEY", "PYTHONPATH", "GIT_CONFIG_COUNT"} & environment.keys()
    assert all(os.environ[key] == value for key, value in values.items())


def test_each_sample_has_empty_separate_app_state(tmp_path):
    left = runner.private_environment(tmp_path / "a", tmp_path, tmp_path / "pyc")
    right = runner.private_environment(tmp_path / "b", tmp_path, tmp_path / "pyc")
    (Path(left["LOUSHANG_HOME"]) / "session").write_text("previous run")
    assert list(Path(right["LOUSHANG_HOME"]).iterdir()) == []
    assert left["PYTHONPYCACHEPREFIX"] == right["PYTHONPYCACHEPREFIX"]


@pytest.mark.parametrize("kind", ["file", "missing", "symlink"])
def test_controlled_home_fingerprint_rejects_non_directory_or_redirected_root(
    tmp_path, kind
):
    root = tmp_path / "ambient-home"
    root.mkdir()
    (root / "sentinel").write_text("unchanged")
    expected = runner.fingerprint_tree(root)
    assert "sentinel" in expected
    moved = tmp_path / "moved-ambient"
    root.rename(moved)
    if kind == "file":
        root.write_text("not a directory")
    elif kind == "symlink":
        root.symlink_to(moved, target_is_directory=True)
        assert runner.fingerprint_tree(moved) == expected
    with pytest.raises((ValueError, FileNotFoundError)):
        runner.fingerprint_tree(root)


@pytest.mark.skipif(sys.platform != "linux", reason="G18 collector is Linux-only")
def test_capture_checks_output_and_preserves_nonzero_exit(tmp_path):
    result = runner.capture(
        [sys.executable, "-I", "-c", "print('bad'); raise SystemExit(7)"],
        cwd=tmp_path,
        env={},
        timeout=5,
    )
    assert result["exit_code"] == 7
    assert result["stdout"] == "bad\n"
    assert not runner.output_matches("cli-help", result)


@pytest.mark.skipif(sys.platform != "linux", reason="G18 collector is Linux-only")
def test_capture_timeout_settles_root_before_returning(tmp_path):
    result = runner.capture(
        [sys.executable, "-I", "-c", "import time; time.sleep(5)"],
        cwd=tmp_path,
        env={},
        timeout=0.05,
    )
    assert result["failure"] == "timeout"
    assert result["exit_code"] != 0
    assert result["elapsed_seconds"] < 2


@pytest.mark.skipif(sys.platform != "linux", reason="G18 collector is Linux-only")
def test_capture_limits_output(tmp_path, monkeypatch):
    result = runner.capture(
        [sys.executable, "-I", "-c", "print('x' * 1000000)"],
        cwd=tmp_path,
        env={},
        timeout=5,
    )
    assert result["failure"] == "output_limit"
    assert len(result["stdout"]) <= runner.LIMIT


@pytest.mark.skipif(sys.platform != "linux", reason="G18 collector is Linux-only")
@pytest.mark.parametrize("detached", [False, True])
def test_exit_zero_with_closed_stdio_descendant_fails_and_is_reaped(tmp_path, detached):
    pid_file = tmp_path / "leftover.pid"
    program = (
        "import pathlib, subprocess, sys; "
        "child = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(60)'], "
        f"start_new_session={detached!r}, stdin=subprocess.DEVNULL, "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid))"
    )
    result = runner.capture(
        [sys.executable, "-I", "-c", program], cwd=tmp_path, env={}, timeout=5
    )
    assert result["exit_code"] == 0
    assert result["failure"] == "observer_cleanup_required"
    assert not runner.output_matches("import-coding", result)
    assert not Path(f"/proc/{int(pid_file.read_text())}").exists()


@pytest.mark.skipif(sys.platform != "linux", reason="G18 collector is Linux-only")
def test_capture_normal_exit_needs_no_cleanup(tmp_path):
    result = runner.capture(
        [sys.executable, "-I", "-c", "pass"], cwd=tmp_path, env={}, timeout=5
    )
    assert result["exit_code"] == 0
    assert result["failure"] is None


@pytest.mark.skipif(sys.platform != "linux", reason="Linux subreaper observation")
@pytest.mark.parametrize("kind", ["double-fork", "zombie"])
def test_capture_rejects_adopted_grandchild_and_unreaped_zombie(tmp_path, kind):
    pid_file = tmp_path / "descendant.pid"
    if kind == "double-fork":
        program = f"""
import os, pathlib, time
path = pathlib.Path({str(pid_file)!r})
child = os.fork()
if child == 0:
    os.setsid()
    if os.fork() == 0:
        for descriptor in (0, 1, 2):
            os.close(descriptor)
        path.write_text(str(os.getpid()))
        time.sleep(60)
    os._exit(0)
os.waitpid(child, 0)
deadline = time.monotonic() + 3
while not path.exists():
    assert time.monotonic() < deadline
    time.sleep(0.01)
"""
    else:
        program = f"""
import os, pathlib
child = os.fork()
if child == 0:
    os._exit(0)
os.waitid(os.P_PID, child, os.WEXITED | os.WNOWAIT)
pathlib.Path({str(pid_file)!r}).write_text(str(child))
"""
    result = runner.capture(
        [sys.executable, "-I", "-c", program], cwd=tmp_path, env={}, timeout=5
    )
    assert result["exit_code"] == 0
    assert result["failure"] == "observer_cleanup_required"
    assert not Path(f"/proc/{int(pid_file.read_text())}").exists()


@pytest.mark.parametrize(
    "case,stdout,valid",
    [
        ("import-coding", "", True),
        ("import-coding", "side effect", False),
        ("cli-help", "", False),
        ("cli-help", "loushang --help --model", True),
        ("cli-version", "0.1.0\n", True),
        ("cli-version", "wrong version", False),
    ],
)
def test_output_assertions_are_not_exit_only(case, stdout, valid):
    result = dict(stdout=stdout, stderr="", exit_code=0, failure=None)
    assert runner.output_matches(case, result) == valid
    result["stderr"] = "unexpected warning"
    assert not runner.output_matches(case, result)


def test_summary_preserves_tail_and_nearest_rank_estimator():
    summary = runner.summarize([1.0] * 19 + [100.0])
    assert summary == dict(
        n=20,
        median_seconds=1,
        min_seconds=1,
        max_seconds=100,
        p95_seconds=1,
        mad_fraction=0,
    )


def test_atomic_report_replacement_retains_partial_failure(tmp_path):
    report = tmp_path / "report.json"
    runner.write_report(report, {"status": "running", "samples": []})
    runner.write_report(
        report, {"status": "failed", "samples": [{"failure": "timeout"}]}
    )
    assert json.loads(report.read_text())["samples"] == [{"failure": "timeout"}]
    assert not report.with_suffix(".next").exists()


@pytest.mark.parametrize(
    "error", [KeyboardInterrupt(), OSError("receipt IO"), TimeoutError("owner")]
)
def test_failed_or_cancelled_attempt_is_published_before_launch_and_retained(
    tmp_path, error
):
    path = tmp_path / "report.json"
    report = {"samples": []}
    attempt = dict(
        case="import-coding", argv=["installed-python", "-I"], cwd=str(tmp_path)
    )

    def fail():
        pending = json.loads(path.read_text())["samples"][0]
        assert pending["argv"] == attempt["argv"]
        assert pending["status"] == "running" and not pending["valid"]
        raise error

    with pytest.raises(type(error)):
        runner.record_attempt(report, path, attempt, fail)
    (sample,) = json.loads(path.read_text())["samples"]
    assert sample["status"] == "failed" and not sample["valid"]
    assert sample["case"] == attempt["case"]
    assert sample["failure"].startswith(type(error).__name__)


def test_aa_refuses_same_installation_before_creating_output(tmp_path):
    with pytest.raises(SystemExit) as error:
        runner.main(
            [
                "--install-a",
                str(tmp_path),
                "--install-b",
                str(tmp_path),
                "--wheel",
                str(tmp_path / "absent.whl"),
                "--output",
                str(tmp_path / "report"),
            ]
        )
    assert error.value.code == 2
    assert not (tmp_path / "report").exists()


@pytest.mark.parametrize("fault", [None, "before", "during", "receipt"])
def test_installation_checks_are_pinned_to_source_receipt(tmp_path, monkeypatch, fault):
    wheel = tmp_path / "input.whl"
    wheel.write_bytes(b"source-verified-wheel")
    expected = runner.digest(wheel)
    called = []

    def inspect(prefix, archive, scratch):
        called.append(archive)
        if fault == "during":
            wheel.write_bytes(b"changed-during-inspection")
        return {"wheel_sha256": "another-snapshot" if fault == "receipt" else expected}

    monkeypatch.setattr(runner, "verify_install", inspect)
    if fault == "before":
        wheel.write_bytes(b"changed-after-source-receipt")
    if fault:
        with pytest.raises(ValueError, match="wheel differs from source receipt"):
            runner.verify_pinned_install(tmp_path, wheel, tmp_path, expected)
    else:
        assert runner.verify_pinned_install(tmp_path, wheel, tmp_path, expected) == {
            "wheel_sha256": expected,
        }
    assert len(called) == (0 if fault == "before" else 1)


@pytest.mark.parametrize("phase", ["aa", "ab"])
@pytest.mark.parametrize(
    "outcome",
    [
        "pass",
        "regression",
        "inconclusive",
        "target-not-met",
        "short",
        "helpers",
        "install",
        "sample",
    ],
)
def test_inert_main_reports_comparison_without_upgrading_collection_success(
    tmp_path, monkeypatch, phase, outcome
):
    from types import SimpleNamespace

    manifest_calls, pins, reports = [], [], []

    def manifest(_):
        manifest_calls.append(True)
        return {
            "helper": "changed"
            if outcome == "helpers" and len(manifest_calls) == 2
            else "same"
        }

    def pin(*_):
        pins.append(True)
        return dict(
            python="changed" if outcome == "install" and len(pins) == 3 else "same",
            dependencies=[],
            entries={
                entry[0]: "target"
                for entry in runner.CASES.values()
                if entry[0] != "import"
            },
        )

    def capture(argv, *, cwd, **_):
        side = Path(argv[0]).parent.parent.name
        duration = 1.0
        if phase == "ab" and side == "b":
            duration = 0.7 if outcome != "target-not-met" else 1.0
            if outcome == "regression" and Path(argv[0]).name == "loushang-plugin":
                duration = 1.2
        if outcome == "inconclusive" and cwd.name.startswith("b1-"):
            duration += 0.3
        if argv[-1] == "--version":
            stdout = "0.1.0"
        elif argv[-1] == "--help":
            stdout = f"usage: {Path(argv[0]).name} --help --model"
        else:
            stdout = ""
        return dict(
            elapsed_seconds=duration,
            stdout=stdout,
            stderr="",
            exit_code=0,
            failure="owner rejected" if outcome == "sample" else None,
        )

    sources = {
        side: dict(
            commit=side,
            lock_sha256="lock",
            wheel_sha256=side if phase == "ab" else "same",
        )
        for side in ("a", "b")
    }
    monkeypatch.setattr(runner.sys, "platform", "linux")
    monkeypatch.setattr(runner.os, "sched_getaffinity", lambda _: {0}, raising=False)
    monkeypatch.setattr(runner.os, "getloadavg", lambda: (0, 0, 0), raising=False)
    monkeypatch.setattr(
        runner,
        "source_pair",
        lambda *_: ({side: tmp_path / side for side in ("a", "b")}, sources),
    )
    monkeypatch.setattr(
        runner, "provenance_module", lambda: SimpleNamespace(helper_manifest=manifest)
    )
    monkeypatch.setattr(runner, "verify_pinned_install", pin)
    monkeypatch.setattr(runner, "capture", capture)
    monkeypatch.setattr(runner, "private_environment", lambda *_: {})
    monkeypatch.setattr(
        runner,
        "digest",
        lambda path: (
            sources[path.name]["wheel_sha256"] if path.name in sources else "helper"
        ),
    )
    # Exercise all real sampling/validation/comparison code, without hundreds of
    # intermediate disk writes or launching Product from this deterministic test.
    monkeypatch.setattr(
        runner, "write_report", lambda _, report: reports.append(report)
    )
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    def temporary(**kwargs):
        assert kwargs["dir"] == tmp_path
        return str(scratch)

    monkeypatch.setattr(runner.tempfile, "mkdtemp", temporary)
    args = [
        "--install-a",
        str(tmp_path / "a"),
        "--install-b",
        str(tmp_path / "b"),
        "--wheel",
        "baseline.whl",
        "--scratch-parent",
        str(tmp_path),
        "--output",
        str(tmp_path / "output"),
    ]
    if outcome == "short":
        args += ["--blocks", "1", "--pairs-per-block", "1"]
    if outcome in {"helpers", "install", "sample"}:
        with pytest.raises(ValueError):
            runner.main(args)
    else:
        assert runner.main(args) == 0
    report = json.loads(json.dumps(reports[-1]))
    assert report["scratch_parent"] == str(tmp_path)
    assert report["scratch_device"] == scratch.stat().st_dev
    if outcome in {"helpers", "install", "sample", "short"}:
        assert report["comparison"]["verdict"] == "not-evaluated"
        assert report["comparison"]["reason"]
        assert report["status"] == (
            "complete-record-only" if outcome == "short" else "failed"
        )
    else:
        assert report["status"] == "complete-record-only"
        expected = (
            "pass"
            if phase == "aa" and outcome in {"regression", "target-not-met"}
            else outcome
        )
        assert report["comparison"]["verdict"] == expected
        assert report["comparison"]["phase"] == phase
        assert set(report["comparison"]["cases"]) == set(runner.CASES)
