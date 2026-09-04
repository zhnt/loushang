from __future__ import annotations

import ast
from pathlib import Path

HOSTING_ROOT = Path("src/loushang/hosting")
BACKEND = HOSTING_ROOT / "_process_backend.py"
HOST = HOSTING_ROOT / "_process_host.py"
ROOT = HOSTING_ROOT / "__init__.py"
HARNESS_PROCESS = Path("src/loushang/harness/workspace/process")
SPECIFICATION = Path(
    "docs/internals/architecture/hosting/process-lifetime-host-h1.md"
)


def _class_methods(path: Path, class_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    target = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    return {
        node.name
        for node in target.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_h1_backend_is_private_and_carries_no_raw_process_identity() -> None:
    root = ROOT.read_text(encoding="utf-8")
    backend = BACKEND.read_text(encoding="utf-8")
    tree = ast.parse(backend)

    assert "_process_backend" not in root
    assert "_process_host" not in root
    assert "_ProcessBackend" not in root
    assert "_ProcessHost" not in root
    assert _class_methods(BACKEND, "_ProcessBackend") == {
        "backend_id",
        "spawn",
        "terminate_tree",
        "kill_tree",
        "close_process_handles",
    }
    assert _class_methods(BACKEND, "_ProcessTransport") == {
        "return_code",
        "read_stdout",
        "read_stderr",
        "write_stdin",
        "close_stdin",
        "wait",
    }
    identifiers = {
        name
        for node in ast.walk(tree)
        for name in (
            (node.id,) if isinstance(node, ast.Name) else ()
        )
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    assert not identifiers.intersection(
        {"pid", "raw_handle", "native_handle", "register_backend"}
    )


def test_h1_has_no_real_spawn_primitive_or_upward_dependency() -> None:
    source = BACKEND.read_text(encoding="utf-8") + HOST.read_text(encoding="utf-8")
    for forbidden in (
        "asyncio.create_subprocess_exec",
        "subprocess.Popen",
        "os.fork",
        "CreateProcess",
        "loushang.harness",
        "loushang.coding",
        "loushang.plugin",
        "loushang.agent",
    ):
        assert forbidden not in source


def test_h1_preserves_current_harness_process_owner() -> None:
    assert HARNESS_PROCESS.is_dir()
    for path in HARNESS_PROCESS.glob("*.py"):
        assert "loushang.hosting" not in path.read_text(encoding="utf-8")


def test_h1_specification_records_private_fake_backed_delivery_boundary() -> None:
    specification = " ".join(
        SPECIFICATION.read_text(encoding="utf-8").split()
    )
    for evidence in (
        "Implementation status: implemented",
        "private and fake-backed",
        "capacity -> preparation -> verify -> spawn/attach -> publication",
        "terminate -> bounded grace -> kill -> reap -> close handles",
        "H2 entry criteria",
        "does not migrate the Current Harness process owner",
        "does not implement H3 inherited endpoints or H4 child sessions",
    ):
        assert evidence in specification


def test_h1_lifecycle_matrix_names_required_adversarial_cases() -> None:
    tests = Path("tests/hosting/test_process_host.py").read_text(encoding="utf-8")
    for case in (
        "natural_exit_releases_capacity_after_owned_cleanup",
        "spawn_failure_and_early_exit_rollback_without_leaks",
        "terminate_uses_grace_then_kill_and_all_waiters_share_exit",
        "close_aggregates_faults_but_attempts_every_reachable_cleanup",
        "start_cancellation_after_attachment_is_shielded_until_reclaimed",
        "cancellation_during_failed_start_rollback_takes_precedence",
        "host_close_fences_and_cancels_pending_start_before_returning",
        "reentrant_host_close_from_preparation_fails_without_deadlock",
        "concurrent_lease_close_has_one_owner_and_delays_cancellation",
        "host_close_is_shared_and_delays_repeated_cancellation",
        "stream_modes_and_read_write_bounds_are_enforced",
        "observation_failure_cannot_control_process_lifecycle",
    ):
        assert f"test_{case}" in tests
