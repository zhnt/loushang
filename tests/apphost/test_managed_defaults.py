from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from loushang.apphost.managed import defaults as module
from loushang.apphost.managed.contracts import ManagedContractError
from loushang.hosting.errors import HostingError, HostingFailureCategory

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux managed defaults")


@pytest.fixture(autouse=True)
def machine(monkeypatch):
    monkeypatch.setattr(module, "linux_machine_key", lambda *, domain: "a" * 32)


def test_defaults_same_from_any_cwd_without_creating_directories(tmp_path, monkeypatch):
    first = module.resolve_managed_defaults(environ={}, home=tmp_path / "home")
    monkeypatch.chdir(tmp_path)
    second = module.resolve_managed_defaults(environ={}, home=tmp_path / "home")
    assert first == second
    assert first.namespace.platform_home == str(tmp_path / "home/.loushang")
    assert first.platform.runtime == Path("/tmp") / f"loushang-{os.getuid()}"
    assert first.temporary_override is None
    assert not list(tmp_path.iterdir())


def test_explicit_root_precedence_and_environment_snapshot(tmp_path):
    env = {"LOUSHANG_HOME": str(tmp_path / "platform"), "LOUSHANG_RUNTIME_DIR": str(tmp_path / "run"),
           "XDG_RUNTIME_DIR": str(tmp_path / "xdg"), "LOUSHANG_TMPDIR": str(tmp_path / "scratch")}
    value = module.resolve_managed_defaults(environ=env, home=tmp_path / "ignored")
    env["LOUSHANG_HOME"] = "/changed"
    assert value.namespace.platform_home == str(tmp_path / "platform")
    assert value.platform.runtime == tmp_path / "run"
    assert value.temporary_override == str(tmp_path / "scratch")
    assert not list(tmp_path.iterdir())


def test_xdg_runtime_precedence(tmp_path):
    result = module.resolve_managed_defaults(environ={"XDG_RUNTIME_DIR": str(tmp_path / "xdg")}, home=tmp_path)
    assert result.platform.runtime == tmp_path / "xdg/loushang"


def test_platform_rejection_before_uid_or_path_lookup(monkeypatch):
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module, "resolve_platform_paths", lambda **k: pytest.fail("unsupported lookup"))
    with pytest.raises(HostingError) as caught:
        module.resolve_managed_defaults(environ={})
    assert caught.value.category == HostingFailureCategory.PLATFORM_UNSUPPORTED


def test_shell_tmpdir_does_not_change_reconnect_namespace(tmp_path):
    before = module.resolve_managed_defaults(environ={}, home=tmp_path)
    after = module.resolve_managed_defaults(environ={"TMPDIR": str(tmp_path / "scratch")}, home=tmp_path)
    assert before == after


def test_explicit_tmp_common_ancestor_is_allowed_when_leaves_are_disjoint(tmp_path):
    value = module.resolve_managed_defaults(environ={"LOUSHANG_TMPDIR": "/tmp"}, home=tmp_path)
    assert value.temporary_override == "/tmp"
    assert value.platform.runtime == Path("/tmp") / f"loushang-{os.getuid()}"


def test_unused_lower_priority_roots_do_not_override_valid_selection(tmp_path):
    env = {"LOUSHANG_HOME": str(tmp_path / "platform"), "LOUSHANG_RUNTIME_DIR": str(tmp_path / "run"),
           "XDG_RUNTIME_DIR": "relative-unused"}
    result = module.resolve_managed_defaults(environ=env, home="relative-unused")
    assert result.namespace.platform_home == str(tmp_path / "platform")
    assert result.platform.runtime == tmp_path / "run"


@pytest.mark.parametrize("key", ["LOUSHANG_HOME", "LOUSHANG_RUNTIME_DIR", "LOUSHANG_TMPDIR", "XDG_RUNTIME_DIR"])
@pytest.mark.parametrize("value", ["relative", " "])
def test_rejects_cwd_dependent_root_overrides(tmp_path, key, value, monkeypatch):
    monkeypatch.setattr(module, "linux_machine_key", lambda **k: pytest.fail("invalid root read machine ID"))
    with pytest.raises(ManagedContractError):
        module.resolve_managed_defaults(environ={key: value}, home=tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("key,suffix", [("LOUSHANG_RUNTIME_DIR", "lmux"), ("LOUSHANG_RUNTIME_DIR", "state"),
    ("LOUSHANG_RUNTIME_DIR", "data"), ("LOUSHANG_TMPDIR", "lmux"), ("LOUSHANG_TMPDIR", "state"),
    ("LOUSHANG_TMPDIR", "data"), ("LOUSHANG_TMPDIR", "run")])
def test_overlapping_roots_rejected_before_creation(tmp_path, key, suffix):
    env = {"LOUSHANG_HOME": str(tmp_path), "LOUSHANG_RUNTIME_DIR": str(tmp_path / "run"), key: str(tmp_path / suffix)}
    with pytest.raises(ManagedContractError):
        module.resolve_managed_defaults(environ=env)
    assert not list(tmp_path.iterdir())
