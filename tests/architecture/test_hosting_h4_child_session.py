from __future__ import annotations

import re
from pathlib import Path

SPECIFICATION = Path(
    "docs/internals/architecture/hosting/atomic-child-session-h4.md"
)


def _section(text: str, heading: str) -> str:
    marker = f"## {heading}\n"
    assert marker in text
    body = text.split(marker, maxsplit=1)[1]
    return body.split("\n## ", maxsplit=1)[0]


def test_h4_is_atomic_protocol_neutral_and_keeps_activation_separate() -> None:
    specification = " ".join(SPECIFICATION.read_text(encoding="utf-8").split())

    for statement in (
        "H4 implements `HOST-CMP-SESSION` as the sole aggregate lifetime owner",
        "every unsuccessful transaction publishes neither constituent lease",
        "owns no protocol framing, handshake, heartbeat, Worker health",
        "H4 completes the five-component Hosting v1 mechanism baseline",
        "Current Harness Worker owner",
    ):
        assert statement in specification


def test_h4_freezes_transaction_order_and_cleanup_debt() -> None:
    specification = SPECIFICATION.read_text(encoding="utf-8")
    section = _section(specification, "Atomic Start Transaction")
    steps = tuple(re.findall(r"^\d+\. (.+);?$", section, re.MULTILINE))

    assert len(steps) == 10
    for earlier, later in (
        ("reserve aggregate session capacity", "reserve process capacity"),
        ("reserve process capacity", "LaunchPreparationLease"),
        ("LaunchPreparationLease", "inherited endpoint pair"),
        ("inherited endpoint pair", "verify_current"),
        ("verify_current", "spawn/contain"),
        ("spawn/contain", "publish one `ChildSessionLease`"),
    ):
        assert section.index(earlier) < section.index(later)

    ownership = " ".join(
        _section(specification, "Ownership And Rollback Matrix").split()
    )
    assert "Primary failure or cancellation remains primary" in ownership
    assert "Failed cleanup retains capacity debt" in ownership
    assert "faults the relevant owner against new work" in ownership
    assert "This rule crosses nested owners" in ownership
    assert "preserves H0 `loushang.hosting/v1` construction compatibility" in section


def test_h4_conformance_inventory_is_complete_and_ordered() -> None:
    section = _section(
        SPECIFICATION.read_text(encoding="utf-8"), "Conformance Inventory"
    )
    assert tuple(re.findall(r"^\| `([^`]+)` \|", section, re.MULTILINE)) == (
        "H4-TXN-ORDER",
        "H4-TXN-ROLLBACK",
        "H4-TXN-CANCEL",
        "H4-LIFE-JOINT",
        "H4-LIFE-DEBT",
        "H4-OBS-CORRELATE",
        "H4-SELECT-SET",
        "H4-NATIVE-ROUNDTRIP",
    )


def test_h4_public_surface_is_restrained_and_concrete_owners_are_private() -> None:
    public_surface = Path("src/loushang/hosting/__init__.py").read_text(
        encoding="utf-8"
    )
    runtime = Path("src/loushang/hosting/runtime.py").read_text(encoding="utf-8")
    session = Path("src/loushang/hosting/_child_session_host.py").read_text(
        encoding="utf-8"
    )

    assert '"create_child_session_host"' in public_surface
    assert "def create_child_session_host(" in runtime
    for private_name in (
        "_ChildSessionHost",
        "_InheritedEndpointHost",
        "_DeferredProcessInheritance",
        "_select_child_session_backends",
    ):
        assert private_name not in public_surface
    assert "_start_with_inheritance(" in session
    assert "HostingComponent.SESSION" in session
    assert "session_id=session_id" in session
    assert "create_endpoint_host" not in public_surface
    assert "create_endpoint_host" not in runtime


def test_h4_platform_set_is_exact_and_windows_shares_one_raw_api() -> None:
    platform = Path("src/loushang/hosting/_endpoint_platform.py").read_text(
        encoding="utf-8"
    )

    assert "def _select_child_session_backends(" in platform
    assert "process=_PosixProcessBackend()" in platform
    assert "endpoint=_PosixEndpointBackend()" in platform
    assert "api = _CtypesWin32Api()" in platform
    assert "_WindowsProcessBackend(max_processes=max_sessions, api=api)" in platform
    assert "api=api" in platform
    assert "process._abort_construction()" in platform
    for fallback in ("localhost", "127.0.0.1", "tempfile", "NamedPipe"):
        assert fallback not in platform


def test_h4_executable_matrix_covers_joint_lifecycle_and_native_factory() -> None:
    tests = Path("tests/hosting/test_child_session_host.py").read_text(
        encoding="utf-8"
    )
    native = Path("tests/hosting/test_native_conformance.py").read_text(
        encoding="utf-8"
    )

    for evidence in (
        "test_child_session_orders_transaction_and_natural_exit_releases_all",
        "test_child_session_validates_initial_topology_before_capacity",
        "test_child_session_revalidates_prepared_topology_before_endpoint",
        "test_child_session_failure_matrix_publishes_neither_and_reclaims_all",
        "test_child_session_backend_mismatch_reclaims_before_spawn",
        "test_child_session_retains_nested_endpoint_acquisition_debt",
        "test_child_session_retains_nested_process_rollback_debt",
        "test_host_close_fences_aggregate_publication_after_process_publication",
        "test_child_session_cancellation_after_process_attachment_rolls_back",
        "test_cancelled_session_close_waiter_does_not_repeat_successful_owner",
        "test_child_session_cleanup_failure_faults_host_and_is_retryable",
        "test_child_session_rollback_failure_retains_capacity_debt",
        "test_child_session_observations_share_correlation_and_cannot_veto",
    ):
        assert evidence in tests
    assert "create_child_session_host" in native
    assert "ChildSessionRequest" in native
