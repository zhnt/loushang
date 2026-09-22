from __future__ import annotations

import builtins
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from loushang.apphost.managed.contracts import (
    ManagedContractError,
    ManagedInstanceRefV1,
    ManagedNamespaceV1,
    ManagedServiceKeyV1,
)
from loushang.apphost.managed.invocation import ManagedChildInvocationV1
from loushang.apphost.managed.paths import resolve_managed_paths
from loushang.coding import managed_local
from loushang.coding import managed_process as module


@pytest.mark.parametrize("frontend", [False])
def test_launch_material_does_not_import_backend(tmp_path, frontend):
    selected = invocation(tmp_path)
    script = """
import sys
from loushang.coding.managed_process import coding_managed_process_request
from loushang.apphost.managed.invocation import ManagedChildInvocationV1
assert 'loushang.coding.managed_local' not in sys.modules
request = coding_managed_process_request(
    ManagedChildInvocationV1.from_json(sys.argv[1]), 7,
    executable=sys.executable, environment={},
)
assert request.argv[2] == 'loushang.coding.managed_process'
assert 'loushang.coding.managed_local' not in sys.modules
"""
    if frontend:
        script = "import loushang.coding.cli.lmux_command\n" + script
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"))
    result = subprocess.run(
        [sys.executable, "-c", script, selected.to_json()],
        env=environment, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert not tuple(tmp_path.iterdir())


def test_backend_import_failure_closes_adopted_endpoint(tmp_path, monkeypatch, capsys):
    selected = invocation(tmp_path)
    closed = []

    class Endpoint:
        def close(self):
            closed.append(True)

    original_import = builtins.__import__

    def import_module(name, *args, **kwargs):
        if name == "managed_local":
            raise ImportError("private-backend-failure")
        return original_import(name, *args, **kwargs)

    for name in ("LOUSHANG_HOME", "LOUSHANG_RUNTIME_DIR", "LOUSHANG_TMPDIR"):
        monkeypatch.setenv(name, "test-original")
    monkeypatch.setattr(module.socket, "socket", lambda **kwargs: Endpoint())
    monkeypatch.setattr(module, "ManagedChildBootstrapV1", lambda *a, **k: pytest.fail("bootstrap before import"))
    monkeypatch.setattr(builtins, "__import__", import_module)
    assert module.main([selected.to_json(), str(tmp_path / "sessions"), "7"]) == 1
    assert closed == [True]
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "managed_process_failed\n"


@pytest.mark.parametrize("mode", ["disabled", "active", "expired"])
def test_process_installs_only_unexpired_explicit_trace(tmp_path, monkeypatch, mode):
    from loushang.apphost.managed.trace_buffer import ManagedTraceBuffer
    from loushang.foundation.observability import get_log
    from loushang.foundation.observability._router import reset_observability

    selected = invocation(tmp_path)
    if mode != "disabled":
        selected = replace(selected, trace_deadline_ms=101000 if mode == "active" else 99000)
    instances = []
    class Bootstrap:
        def __init__(self, *args, **kwargs):
            self.trace = None
            self.record = None
            self.closed = False
            instances.append(self)
        def open(self, **kwargs):
            pass
        def managed_mux_binding(self, **kwargs):
            return object()
        def output_capture_factory(self, **kwargs):
            return object()
        def prepare_trace(self, *, deadline):
            assert deadline == 101
            self.trace = ManagedTraceBuffer(selected.instance.instance_id, deadline, clock=lambda: 100)
            return self.trace
        def bind(self, app):
            pass
        def trace_sink_installed(self, buffer):
            assert buffer is self.trace
        def run_process(self):
            get_log("test").debug_event("turn.start.performance", "turn", total_ms=1, prompt="secret")
            if self.trace is not None:
                self.trace.fence()
            return 0
        def close(self):
            self.closed = True
            if self.trace is not None:
                self.record = self.trace.take()
    for name in ("LOUSHANG_HOME", "LOUSHANG_RUNTIME_DIR", "LOUSHANG_TMPDIR"):
        monkeypatch.setenv(name, "test-original")
    monkeypatch.setattr(module, "monotonic", lambda: 100)
    monkeypatch.setattr(module.socket, "socket", lambda **kwargs: object())
    monkeypatch.setattr(module, "ManagedChildBootstrapV1", Bootstrap)
    monkeypatch.setattr(managed_local, "create_coding_managed_local_launch", lambda *args, **kwargs: object())
    monkeypatch.setattr(managed_local, "CodingManagedLocalCommandV1", lambda *args, **kwargs: object())
    reset_observability()
    try:
        assert module._run([selected.to_json(), str(tmp_path / "sessions"), "7"]) == 0
        assert instances[0].closed
        assert (instances[0].record is not None) == (mode == "active")
        if mode == "active":
            assert b"secret" not in instances[0].record
    finally:
        reset_observability()


def invocation(tmp_path, product="coding"):
    namespace = ManagedNamespaceV1(str(tmp_path / "platform"), 1000, "a" * 32)
    service = ManagedServiceKeyV1(product, str(tmp_path))
    return ManagedChildInvocationV1(
        namespace, service, ManagedInstanceRefV1(namespace.namespace_key, service.service_id, "b" * 32),
        "c" * 32, str(tmp_path / "runtime"),
    )


@pytest.mark.parametrize("override", [False, True])
def test_request_is_pure_and_freezes_environment_without_mutating_input(tmp_path, monkeypatch, override):
    selected = invocation(tmp_path)
    if override:
        selected = replace(selected, temporary_override=str(tmp_path / "scratch"))
    environment = {"LOUSHANG_HOME": "/other", "LOUSHANG_RUNTIME_DIR": "/elsewhere", "LOUSHANG_TMPDIR": "/mutable", "EMPTY": "", "LABEL": "中文"}
    original = dict(environment)
    monkeypatch.setattr(module.socket, "socket", lambda *a, **k: pytest.fail("pure request opened socket"))
    value = module.coding_managed_process_request(selected, 7, executable=sys.executable, environment=environment)
    assert environment == original
    assert value.argv == (
        sys.executable, "-m", "loushang.coding.managed_process", selected.to_json(),
        str(tmp_path / "platform/data/sessions"), "7",
    )
    assert dict(value.effective_environment) == {
        **original, "LOUSHANG_HOME": selected.namespace.platform_home, "LOUSHANG_RUNTIME_DIR": selected.runtime_root,
        "LOUSHANG_TMPDIR": str(resolve_managed_paths(selected.namespace, selected.service, selected.instance,
                                                    runtime_root=selected.runtime_root,
                                                    temporary_override=selected.temporary_override).temporary),
    }
    assert not tuple(tmp_path.iterdir())


@pytest.mark.parametrize("kind", ["product", "bool_fd", "stdin", "huge_fd", "executable", "session_root"])
def test_request_rejects_invalid_facts_without_io(tmp_path, monkeypatch, kind):
    selected = invocation(tmp_path, "work" if kind == "product" else "coding")
    descriptor = {"bool_fd": True, "stdin": 0, "huge_fd": 2**31}.get(kind, 7)
    from pathlib import Path

    monkeypatch.setattr(module.socket, "socket", lambda *a, **k: pytest.fail("invalid request opened socket"))
    with pytest.raises(ManagedContractError):
        module.coding_managed_process_request(
            selected, descriptor, executable="relative" if kind == "executable" else sys.executable,
            environment={}, session_root=Path("relative") if kind == "session_root" else None,
        )
    assert not tuple(tmp_path.iterdir())


@pytest.mark.parametrize("kind", ["count", "json", "duplicate", "fd", "product"])
def test_invalid_entry_is_bounded_and_never_adopts_descriptor(tmp_path, monkeypatch, capsys, kind):
    selected = invocation(tmp_path, "work" if kind == "product" else "coding")
    payload = selected.to_json()
    if kind == "json":
        payload = "private-secret-invalid"
    elif kind == "duplicate":
        payload = payload.replace("{", '{"version":"private-secret",', 1)
    arguments = [payload, str(tmp_path / "sessions"), "０" if kind == "fd" else "7"]
    if kind == "count":
        arguments = []
    monkeypatch.setattr(module.socket, "socket", lambda *a, **k: pytest.fail("invalid entry adopted fd"))
    assert module.main(arguments) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "managed_process_failed\n"
    assert not tuple(tmp_path.iterdir())
