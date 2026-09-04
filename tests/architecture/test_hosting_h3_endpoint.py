from __future__ import annotations

import re
from pathlib import Path

SPECIFICATION = Path(
    "docs/internals/architecture/hosting/inherited-peer-endpoint-h3.md"
)


def _section(text: str, heading: str) -> str:
    marker = f"## {heading}\n"
    assert marker in text
    body = text.split(marker, maxsplit=1)[1]
    return body.split("\n## ", maxsplit=1)[0]


def test_h3_scope_is_private_protocol_neutral_at_its_slice_boundary() -> None:
    specification = " ".join(SPECIFICATION.read_text(encoding="utf-8").split())

    for statement in (
        "H3 implements `HOST-CMP-ENDPOINT` as a private resource owner",
        "does not expose an endpoint factory publicly",
        "Atomic composition and the public `ChildSessionHostingPort` were "
        "deliberately deferred to H4",
        "No descriptor, handle, address, token, or endpoint name enters argv",
        "interprets none of its bytes",
    ):
        assert statement in specification


def test_h3_freezes_exact_platform_mechanisms_and_no_fallback() -> None:
    specification = SPECIFICATION.read_text(encoding="utf-8")
    normalized = " ".join(specification.split())

    for mechanism in (
        "socket.socketpair",
        "close_fds=True",
        "start_new_session=True",
        "PROC_THREAD_ATTRIBUTE_HANDLE_LIST",
        "PROC_THREAD_ATTRIBUTE_JOB_LIST",
        "CreateProcessW",
        "CancelSynchronousIo",
    ):
        assert mechanism in specification
    for forbidden in (
        "No `pass_fds`, listener, filesystem rendezvous, TCP fallback",
        "no unbounded application queue",
        "no public raw endpoint factory",
    ):
        assert forbidden in normalized


def test_h3_conformance_inventory_is_complete_and_ordered() -> None:
    section = _section(
        SPECIFICATION.read_text(encoding="utf-8"), "Conformance Inventory"
    )
    assert tuple(re.findall(r"^\| `([^`]+)` \|", section, re.MULTILINE)) == (
        "H3-OWNER-CAPACITY",
        "H3-OWNER-BOUNDS",
        "H3-OWNER-CANCEL",
        "H3-TRANSFER-ONCE",
        "H3-POSIX-PAIR",
        "H3-POSIX-FD",
        "H3-WIN-PAIR",
        "H3-WIN-HANDLE",
        "H3-WIN-CANCEL",
        "H3-SELECT",
    )


def test_h3_sources_keep_endpoint_composition_private() -> None:
    public_surface = Path("src/loushang/hosting/__init__.py").read_text(
        encoding="utf-8"
    )
    runtime = Path("src/loushang/hosting/runtime.py").read_text(encoding="utf-8")
    process_host = Path("src/loushang/hosting/_process_host.py").read_text(
        encoding="utf-8"
    )
    posix = Path("src/loushang/hosting/_posix_endpoint.py").read_text(
        encoding="utf-8"
    )
    windows = Path("src/loushang/hosting/_windows_endpoint.py").read_text(
        encoding="utf-8"
    )
    raw_windows = Path("src/loushang/hosting/_win32_process.py").read_text(
        encoding="utf-8"
    )

    for private_name in (
        "_InheritedEndpointHost",
        "_SingleUseProcessInheritance",
        "_select_endpoint_backend",
        "create_endpoint_host",
    ):
        assert private_name not in public_surface
    assert "create_endpoint_host" not in runtime
    assert "socket.socketpair" in posix
    assert "_SingleUseProcessInheritance" in posix
    assert "create_pipe(child_reads=True)" in windows
    assert "create_pipe(child_reads=False)" in windows
    assert "_CancelSynchronousIo" in raw_windows
    assert "def _start_with_inheritance(" in process_host
    assert "inheritance=inheritance" in process_host
    endpoint_host = Path("src/loushang/hosting/_endpoint_host.py").read_text(
        encoding="utf-8"
    )
    assert "HostingComponent.ENDPOINT" in endpoint_host
    assert "HostingObservationSink" in endpoint_host


def test_h3_reserves_process_stream_topology_for_single_owner() -> None:
    specification = " ".join(SPECIFICATION.read_text(encoding="utf-8").split())
    posix_process = Path("src/loushang/hosting/_posix_process.py").read_text(
        encoding="utf-8"
    )
    windows_process = Path("src/loushang/hosting/_windows_process.py").read_text(
        encoding="utf-8"
    )

    assert "must therefore declare `stdin=CLOSED` and `stdout=DISCARD`" in specification
    for source in (posix_process, windows_process):
        assert "request.streams.stdin is not ProcessStdinMode.CLOSED" in source
        assert "request.streams.stdout is not ProcessStdoutMode.DISCARD" in source
