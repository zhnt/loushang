"""Native Windows managed addressing requires no filesystem admission."""

from __future__ import annotations

import sys

import pytest

from loushang.apphost.managed.contracts import ManagedServiceKeyV1
from loushang.apphost.managed.defaults import resolve_managed_defaults
from loushang.apphost.managed.paths import resolve_managed_service_paths

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows user and machine identity")


def test_windows_managed_defaults_are_stable_without_creating_directories(tmp_path):
    home = tmp_path / "isolated home"
    resolved = resolve_managed_defaults(environ={"LOUSHANG_HOME": str(home)})
    again = resolve_managed_defaults(environ={"LOUSHANG_HOME": str(home)})
    assert resolved.namespace == again.namespace
    assert resolved.namespace.user_id.startswith("S-1-")
    service = ManagedServiceKeyV1("coding", str(home))
    paths = resolve_managed_service_paths(resolved.namespace, service, runtime_root=str(resolved.platform.runtime))
    assert paths.connection.is_relative_to(resolved.platform.runtime)
    assert paths.application.is_relative_to(home)
    assert not home.exists()
