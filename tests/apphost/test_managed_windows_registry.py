"""Exercise native namespace admission and Mux registry persistence."""

from __future__ import annotations

import sys
from time import monotonic

import pytest

from loushang.apphost.managed.contracts import ManagedServiceKeyV1
from loushang.apphost.managed.defaults import resolve_managed_defaults
from loushang.apphost.managed.namespace_admission import ManagedNamespaceAdmissionV1
from loushang.apphost.managed.registry import ManagedMuxReservationV1

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows managed registry")


def test_windows_namespace_initializes_and_reopens_registry(tmp_path):
    home = tmp_path / "managed home #1"
    resolved = resolve_managed_defaults(environ={"LOUSHANG_HOME": str(home)})
    runtime = str(resolved.platform.runtime)
    request = ManagedMuxReservationV1(
        "dev", ManagedServiceKeyV1("coding", str(tmp_path)), "b" * 32,
    )

    initial = ManagedNamespaceAdmissionV1(
        resolved.namespace, runtime_root=runtime, create_if_missing=True,
    )
    try:
        registry = initial.open(deadline=monotonic() + 20)
        assert registry.reserve_mux(request) == request
    finally:
        initial.close()

    existing = ManagedNamespaceAdmissionV1(resolved.namespace, runtime_root=runtime)
    try:
        registry = existing.open(deadline=monotonic() + 20)
        assert registry.resolve("dev") == request
    finally:
        existing.close()
