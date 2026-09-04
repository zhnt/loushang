from __future__ import annotations

import re
from pathlib import Path

SPECIFICATION = Path(
    "docs/internals/architecture/hosting/process-platform-h2.md"
)


def _section(text: str, heading: str) -> str:
    marker = f"## {heading}\n"
    assert marker in text
    body = text.split(marker, maxsplit=1)[1]
    return body.split("\n## ", maxsplit=1)[0]


def _table_ids(text: str, heading: str) -> tuple[str, ...]:
    section = _section(text, heading)
    return tuple(re.findall(r"^\| `([^`]+)` \|", section, re.MULTILINE))


def test_h2a_freezes_three_slice_boundary_and_no_activation() -> None:
    specification = SPECIFICATION.read_text(encoding="utf-8")
    normalized = " ".join(specification.split())

    for statement in (
        "Delivery status: H2a, H2b, and H2c implemented; compatibility remains dark",
        "H2a | exact platform capability contract",
        "H2b | private POSIX process-group and Windows Job Object backends",
        "H2c | Harness compatibility request/lease/preparation adapters",
        "H2c is dark: no production composition root switches",
        "does not implement inherited peer endpoints, Child Session Host",
    ):
        assert statement in normalized


def test_h2a_requires_atomic_tree_ownership_and_no_weaker_fallback() -> None:
    specification = SPECIFICATION.read_text(encoding="utf-8")
    normalized = " ".join(specification.split())

    for mechanism in (
        "start_new_session=True",
        "PROC_THREAD_ATTRIBUTE_JOB_LIST",
        "PROC_THREAD_ATTRIBUTE_HANDLE_LIST",
        "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE",
        "root exit versus owned-tree settlement",
    ):
        assert mechanism in specification
    for forbidden_fallback in (
        "no fallback to root-only `terminate`",
        "root-only `kill`",
        "`taskkill`",
        "`close_fds=False`",
    ):
        assert forbidden_fallback in normalized


def test_h2a_inventory_covers_each_platform_and_compatibility() -> None:
    assert _table_ids(
        SPECIFICATION.read_text(encoding="utf-8"), "Conformance Inventory"
    ) == (
        "H2-POSIX-SPAWN",
        "H2-POSIX-TREE",
        "H2-POSIX-CANCEL",
        "H2-POSIX-FD",
        "H2-WIN-SPAWN",
        "H2-WIN-TREE",
        "H2-WIN-CANCEL",
        "H2-WIN-HANDLE",
        "H2-SELECT",
        "H2-COMPAT",
    )


def test_h2a_keeps_sealed_descriptor_gap_explicit_and_fail_closed() -> None:
    compatibility = " ".join(
        _section(
            SPECIFICATION.read_text(encoding="utf-8"),
            "H2c Harness Compatibility Boundary",
        ).split()
    )
    for statement in (
        "Current managed sealed-executable path",
        "H0 public request intentionally cannot represent",
        "keep that case on the Current owner",
        "never infer an FD from argv",
        "executable fail-closed gate for the sealed-descriptor case",
    ):
        assert statement in compatibility


def test_h2b_factory_is_restrained_and_platform_backends_stay_private() -> None:
    public_surface = Path("src/loushang/hosting/__init__.py").read_text(
        encoding="utf-8"
    )
    runtime = Path("src/loushang/hosting/runtime.py").read_text(encoding="utf-8")

    assert '"create_process_host"' in public_surface
    assert "_select_process_backend(max_processes=max_processes)" in runtime
    for private_name in (
        "_PosixProcessBackend",
        "_WindowsProcessBackend",
        "_ProcessBackend",
        "_ProcessTransport",
    ):
        assert private_name not in public_surface


def test_h2b_platform_sources_encode_atomic_ownership_mechanics() -> None:
    posix = Path("src/loushang/hosting/_posix_process.py").read_text(
        encoding="utf-8"
    )
    windows = Path("src/loushang/hosting/_win32_process.py").read_text(
        encoding="utf-8"
    )

    for statement in (
        "start_new_session=True",
        "close_fds=True",
        'getattr(os, "killpg", None)',
        "_root_identity_was_reused",
    ):
        assert statement in posix
    for statement in (
        "_PROC_THREAD_ATTRIBUTE_JOB_LIST",
        "_PROC_THREAD_ATTRIBUTE_HANDLE_LIST",
        "_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE",
        "_CreateProcessW",
        "_TerminateJobObject",
    ):
        assert statement in windows


def test_h2b_requires_retryable_platform_cleanup_debt_evidence() -> None:
    tests = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in (
            "tests/hosting/test_process_host.py",
            "tests/hosting/test_posix_process.py",
            "tests/hosting/test_windows_process.py",
        )
    )
    for case in (
        "test_force_settlement_timeout_retains_owner_until_tree_retry",
        "test_posix_pending_root_eperm_retains_owner_for_host_close_retry",
        "test_posix_lingering_descendant_eperm_retains_owner_for_retry",
        "test_windows_published_process_retries_failed_close_handle",
    ):
        assert case in tests


def test_h2c_compatibility_adapter_is_dark_and_sealed_fd_fails_closed() -> None:
    harness_process = Path("src/loushang/harness/workspace/process")
    adapter = harness_process / "hosting_compat.py"
    source = adapter.read_text(encoding="utf-8")

    assert "_process_inherited_file_descriptors" in source
    assert "HostingCompatibilityUnavailableError" in source
    assert "create_process_host" in source
    for path in Path("src/loushang/harness").rglob("*.py"):
        if path == adapter:
            continue
        assert "HostingProcessHostAdapter" not in path.read_text(encoding="utf-8")
