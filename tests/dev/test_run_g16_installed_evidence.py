from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import zipfile
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts/dev/run_g16_installed_evidence.py"
)
_SPEC = importlib.util.spec_from_file_location("run_g16_installed_evidence", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
runner = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(runner)


_PACKAGE = {
    "loushang/example.py": b"selected source",
    "loushang/data.json": b'{"selected": true}',
}


def _source_wheel(root, contents=None):
    for name, value in _PACKAGE.items():
        source = root / "src" / name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(value)
    wheel = root / "loushang-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, value in (_PACKAGE if contents is None else contents).items():
            archive.writestr(name, value)
    return wheel


def test_g16_runner_binds_installation_to_wheel_digest_and_removes_source_environment(
    tmp_path,
    monkeypatch,
):
    wheel = _source_wheel(tmp_path)
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    calls = []
    monkeypatch.setattr(runner, "_ROOT", tmp_path)
    monkeypatch.setattr(runner.os, "environ", {})
    monkeypatch.setattr(runner.shutil, "which", lambda name: "/fake/uv")
    monkeypatch.setattr(
        runner, "_run", lambda argv, **kwargs: calls.append((argv, kwargs))
    )
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        monkeypatch.setenv(name, "untrusted/source")
    assert runner.main(["--wheel", str(wheel), "--platform", sys.platform]) == 0
    install = next(argv for argv, _ in calls if "install" in argv)
    assert "loushang @ " + wheel.as_uri() + "#sha256=" + digest in install
    probe = next(argv for argv, _ in calls if "-c" in argv)
    assert probe[-2:] == [digest, str(wheel)] and "-I" in probe
    invocation = next(argv for argv, _ in calls if "pytest" in argv)
    assert "-I" in invocation and f"pythonpath={tmp_path}" in invocation
    for _, kwargs in calls:
        environment = kwargs["environment"]
        assert not {"pythonpath", "pythonhome", "virtual_env"} & {
            name.casefold() for name in environment
        }
        assert kwargs["timeout"] > 0


def test_g16_runner_rejects_wrong_native_platform_before_installation(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        runner, "_run", lambda *args, **kwargs: pytest.fail("unexpected IO")
    )
    other = "win32" if sys.platform != "win32" else "linux"
    with pytest.raises(SystemExit) as error:
        runner.main(["--wheel", str(tmp_path / "absent.whl"), "--platform", other])
    assert error.value.code == 2


@pytest.mark.parametrize("fail_install", [False, True])
def test_g16_runner_keeps_temporary_work_outside_uv_cache_and_cleans_it(
    tmp_path, monkeypatch, fail_install
):
    wheel = _source_wheel(tmp_path)
    cache = tmp_path / ".uv-cache"
    temporary_roots = []
    monkeypatch.setattr(runner, "_ROOT", tmp_path)
    monkeypatch.setattr(runner.os, "environ", {})
    monkeypatch.setattr(runner.shutil, "which", lambda name: "/fake/uv")

    def run(argv, *, cwd, **kwargs):
        assert not cwd.is_relative_to(cache)
        if "venv" in argv:
            target = Path(argv[-1])
            assert not target.is_relative_to(cache)
            assert target.parent == cwd
            assert cwd.parent == tmp_path / ".artifacts"
            assert cwd.is_dir()
            temporary_roots.append(cwd)
        if "install" in argv and fail_install:
            raise RuntimeError("installation failed")

    monkeypatch.setattr(runner, "_run", run)
    arguments = ["--wheel", str(wheel), "--platform", sys.platform]
    if fail_install:
        with pytest.raises(RuntimeError, match="installation failed"):
            runner.main(arguments)
    else:
        assert runner.main(arguments) == 0
    assert len(temporary_roots) == 1
    assert not temporary_roots[0].exists()
    assert cache.is_dir()


@pytest.mark.parametrize(
    "fault", ["stale-module", "missing-module", "changed-module", "changed-asset"]
)
def test_g16_runner_rejects_stale_build_before_installation(
    tmp_path, monkeypatch, fault
):
    contents = dict(_PACKAGE)
    if fault == "stale-module":
        contents["loushang/deleted.py"] = b"obsolete build cache"
    elif fault == "missing-module":
        del contents["loushang/example.py"]
    else:
        name = (
            "loushang/example.py" if fault == "changed-module" else "loushang/data.json"
        )
        contents[name] = b"obsolete build bytes"
    wheel = _source_wheel(tmp_path, contents)
    calls = []
    monkeypatch.setattr(runner, "_ROOT", tmp_path)
    monkeypatch.setattr(runner.os, "environ", {})
    monkeypatch.setattr(runner.shutil, "which", lambda name: "/fake/uv")
    monkeypatch.setattr(runner, "_run", lambda argv, **kwargs: calls.append(argv))
    with pytest.raises(ValueError, match="wheel.*source"):
        runner.main(["--wheel", str(wheel), "--platform", sys.platform])
    assert not (tmp_path / ".uv-cache").exists()
    assert calls == []


def test_g16_probe_rejects_installed_byte_mismatch_without_trusting_metadata_hash(
    tmp_path,
    monkeypatch,
):
    wheel = tmp_path / "loushang-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("loushang/example.py", "selected artifact")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    prefix = tmp_path / "isolated"
    module = prefix / "loushang/example.py"
    module.parent.mkdir(parents=True)
    module.write_text("selected artifact")
    package = SimpleNamespace(
        read_text=lambda name: json.dumps({"url": wheel.as_uri(), "archive_info": {}}),
        locate_file=lambda name: prefix / name,
    )
    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.setattr(sys, "argv", ["probe", digest, str(wheel)])
    monkeypatch.setattr(metadata, "distribution", lambda name: package)
    monkeypatch.setattr(
        importlib, "import_module", lambda name: SimpleNamespace(__file__=str(module))
    )
    exec(runner._PROBE, {})
    module.write_text("stale editable contents")
    with pytest.raises(AssertionError, match="installed bytes differ"):
        exec(runner._PROBE, {})
