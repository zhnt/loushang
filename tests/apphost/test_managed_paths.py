from __future__ import annotations

from dataclasses import replace
from pathlib import Path, PurePosixPath

import pytest

from loushang.apphost.managed.contracts import (
    ManagedContractError,
    ManagedInstanceRefV1,
    ManagedNamespaceV1,
    ManagedServiceKeyV1,
)
from loushang.apphost.managed.paths import resolve_managed_paths


def _values(home="/private/home", workspace="/workspace"):
    namespace = ManagedNamespaceV1(home, 1000, "a" * 32)
    service = ManagedServiceKeyV1("coding", workspace)
    instance = ManagedInstanceRefV1(namespace.namespace_key, service.service_id, "b" * 32)
    return namespace, service, instance


def test_managed_layout_is_pure_and_does_not_move_sessions(monkeypatch):
    def no_io(*args, **kwargs):
        raise AssertionError("pure layout may not inspect the filesystem")

    monkeypatch.setattr(Path, "resolve", no_io)
    monkeypatch.setattr(Path, "stat", no_io)
    namespace, service, instance = _values()
    paths = resolve_managed_paths(namespace, service, instance, runtime_root="/run/user/1000")
    root = PurePosixPath("/private/home/lmux/machines") / namespace.machine_id
    server = root / "servers" / service.service_id
    assert paths.registry == root / "registry"
    assert paths.lifecycle == root / "lifecycle" / service.service_id
    assert paths.application == server / "state/application"
    assert paths.control == server / "state/control"
    assert paths.logs == server / "logs"
    assert paths.temporary == server / "tmp" / instance.instance_id
    assert paths.cache == root / "cache"
    runtime = PurePosixPath("/run/user/1000/lmux") / namespace.namespace_key / service.service_id
    assert paths.connection == runtime / "connection"
    assert paths.runtime_control == runtime / "control"
    assert "private" not in repr(paths)
    assert not hasattr(paths, "sessions")


def test_explicit_temporary_root_and_instance_are_separate():
    namespace, service, instance = _values()
    kwargs = {"runtime_root": "/run/user/1000", "temporary_override": "/scratch"}
    paths = resolve_managed_paths(namespace, service, instance, **kwargs)
    newer = resolve_managed_paths(
        namespace, service, replace(instance, instance_id="c" * 32), **kwargs
    )
    assert paths.temporary == (
        PurePosixPath("/scratch/lmux") / namespace.namespace_key / service.service_id / instance.instance_id
    )
    assert paths.temporary != newer.temporary
    assert paths.lifecycle == newer.lifecycle
    assert paths.connection == newer.connection
    assert paths.application == newer.application


def test_isolated_home_and_workspace_do_not_share_runtime_records():
    original = resolve_managed_paths(*_values(), runtime_root="/run/user/1000")
    other_home = resolve_managed_paths(*_values(home="/other"), runtime_root="/run/user/1000")
    other_workspace = resolve_managed_paths(*_values(workspace="/another"), runtime_root="/run/user/1000")
    assert len({original.connection, other_home.connection, other_workspace.connection}) == 3
    assert len({original.application, other_home.application, other_workspace.application}) == 3


def test_reference_mismatch_never_produces_paths():
    namespace, service, instance = _values()
    for changed in (replace(instance, namespace_key="c" * 64),
                    replace(instance, service_id="d" * 64)):
        with pytest.raises(ManagedContractError):
            resolve_managed_paths(namespace, service, changed, runtime_root="/run/user/1000")


@pytest.mark.parametrize("runtime,temporary", [
    ("relative", None), ("/private/home/lmux", None),
    ("/run/user/1000", "/private/home/lmux"),
    ("/run/user/1000", "/run/user/1000"),
    ("/run/user/1000", "relative"),
])
def test_reject_lexical_overlap_before_any_native_admission(runtime, temporary):
    with pytest.raises(ManagedContractError):
        resolve_managed_paths(*_values(), runtime_root=runtime, temporary_override=temporary)
