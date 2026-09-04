from __future__ import annotations

import asyncio
import os

import pytest

from loushang.hosting import (
    HostingError,
    HostingFailureCategory,
    _endpoint_platform,
    _platform,
    _win32_process,
    _windows_endpoint,
    _windows_process,
)


def test_platform_selector_chooses_exact_running_backend() -> None:
    backend = _platform._select_process_backend(max_processes=1)
    try:
        assert backend.backend_id == {
            "posix": "posix-process-group-v1",
            "nt": "windows-job-v1",
        }[os.name]
    finally:
        asyncio.run(backend.close_backend())


def test_platform_selector_rejects_unknown_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_platform.os, "name", "unsupported")
    with pytest.raises(HostingError) as caught:
        _platform._select_process_backend(max_processes=1)
    assert caught.value.category is HostingFailureCategory.PLATFORM_UNSUPPORTED


def test_child_session_selector_builds_one_exact_compatible_set() -> None:
    backends = _endpoint_platform._select_child_session_backends(
        max_sessions=1,
        endpoint_io_settlement_seconds=1.0,
    )
    try:
        assert (backends.process.backend_id, backends.endpoint.backend_id) == {
            "posix": ("posix-process-group-v1", "posix-socketpair-v1"),
            "nt": ("windows-job-v1", "windows-anonymous-pipes-v1"),
        }[os.name]
    finally:
        asyncio.run(backends.process.close_backend())
        asyncio.run(backends.endpoint.close_backend())


def test_child_session_selector_rejects_unknown_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_endpoint_platform.os, "name", "unsupported")
    with pytest.raises(HostingError) as caught:
        _endpoint_platform._select_child_session_backends(
            max_sessions=1,
            endpoint_io_settlement_seconds=1.0,
        )
    assert caught.value.category is HostingFailureCategory.PLATFORM_UNSUPPORTED


def test_windows_child_session_selector_shares_one_api_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = object()
    captured: dict[str, object] = {}

    class _ProcessBackend:
        backend_id = "windows-job-v1"

        def __init__(self, *, max_processes: int, api: object) -> None:
            captured["process_limit"] = max_processes
            captured["process_api"] = api

        def _abort_construction(self) -> None:
            raise AssertionError("successful construction must not abort")

    class _EndpointBackend:
        backend_id = "windows-anonymous-pipes-v1"

        def __init__(
            self,
            *,
            max_endpoints: int,
            io_settlement_seconds: float,
            api: object,
        ) -> None:
            captured["endpoint_limit"] = max_endpoints
            captured["endpoint_timeout"] = io_settlement_seconds
            captured["endpoint_api"] = api

    monkeypatch.setattr(_endpoint_platform.os, "name", "nt")
    monkeypatch.setattr(_win32_process, "_CtypesWin32Api", lambda: token)
    monkeypatch.setattr(_windows_process, "_WindowsProcessBackend", _ProcessBackend)
    monkeypatch.setattr(_windows_endpoint, "_WindowsEndpointBackend", _EndpointBackend)

    backends = _endpoint_platform._select_child_session_backends(
        max_sessions=3,
        endpoint_io_settlement_seconds=2.5,
    )

    assert backends.process.backend_id == "windows-job-v1"
    assert backends.endpoint.backend_id == "windows-anonymous-pipes-v1"
    assert captured == {
        "process_limit": 3,
        "process_api": token,
        "endpoint_limit": 3,
        "endpoint_timeout": 2.5,
        "endpoint_api": token,
    }


def test_windows_child_session_selector_aborts_partial_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = object()
    process_instances: list[object] = []

    class _ProcessBackend:
        backend_id = "windows-job-v1"

        def __init__(self, *, max_processes: int, api: object) -> None:
            assert max_processes == 2
            assert api is token
            self.abort_calls = 0
            process_instances.append(self)

        def _abort_construction(self) -> None:
            self.abort_calls += 1

    class _EndpointBackend:
        def __init__(self, **kwargs: object) -> None:
            del kwargs
            raise RuntimeError("endpoint construction failed")

    monkeypatch.setattr(_endpoint_platform.os, "name", "nt")
    monkeypatch.setattr(_win32_process, "_CtypesWin32Api", lambda: token)
    monkeypatch.setattr(_windows_process, "_WindowsProcessBackend", _ProcessBackend)
    monkeypatch.setattr(_windows_endpoint, "_WindowsEndpointBackend", _EndpointBackend)

    with pytest.raises(RuntimeError, match="endpoint construction failed"):
        _endpoint_platform._select_child_session_backends(
            max_sessions=2,
            endpoint_io_settlement_seconds=1.0,
        )

    assert len(process_instances) == 1
    assert process_instances[0].abort_calls == 1  # type: ignore[attr-defined]
