from __future__ import annotations

import ast
from pathlib import Path

RECORD = Path(
    "docs/internals/architecture/hosting/validation/"
    "managed-launch-preparation-h6-harness-parity.md"
)
ADAPTER = Path("src/loushang/harness/worker/hosting_adapter.py")
WORKER_TESTS = Path("tests/harness/worker/test_hosting_adapter.py")
CURRENT_LAUNCH_TESTS = Path("tests/harness/worker/test_launch.py")
CURRENT_SUPERVISOR_TESTS = Path("tests/harness/worker/test_supervisor.py")
SELECTION = Path("src/loushang/harness/worker/owner_selection.py")
WORKFLOW = Path(".github/workflows/hosting-quality.yml")
HOSTING_PUBLIC = (
    Path("src/loushang/hosting/__init__.py"),
    Path("src/loushang/hosting/contracts.py"),
    Path("src/loushang/hosting/runtime.py"),
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _resolve_import_from(path: Path, node: ast.ImportFrom) -> set[str]:
    if node.module is None:
        return set()
    module = node.module
    if node.level != 0:
        package = list(path.with_suffix("").parts[1:-1])
        retained = len(package) - (node.level - 1)
        if retained >= 0:
            module = ".".join((*package[:retained], *node.module.split(".")))
    return {module, *(f"{module}.{alias.name}" for alias in node.names)}


def _imports(path: Path) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(ast.parse(_read(path), filename=str(path))):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.update(_resolve_import_from(path, node))
    return imports


def test_h6_4_bridge_is_nominal_narrow_and_does_not_select_a_profile() -> None:
    adapter = _read(ADAPTER)
    public = "\n".join(_read(path) for path in HOSTING_PUBLIC)

    for statement in (
        "class _ManagedWorkerLaunchPreparationPort(",
        "_ManagedLaunchPreparationPort,",
        "isinstance(delegate, _ManagedLaunchPreparationPort)",
        "await self._managed_delegate.prepare_managed(request, capture)",
        "lease=self._wrap(result.lease)",
        "binding=result.binding",
    ):
        assert statement in adapter
    for forbidden in (
        "_LaunchCaptureSpec",
        "_PosixStaticLaunchCaptureSpec",
        "_WindowsRestrictedLaunchCaptureSpec",
        "profile_id=",
    ):
        assert forbidden not in adapter
    for private_name in (
        "_ManagedLaunchPreparationPort",
        "_ManagedLaunchPreparationResult",
        "_LaunchCapturePort",
    ):
        assert private_name not in public


def test_h6_4_private_friend_import_is_confined_to_the_worker_adapter() -> None:
    private_module = "loushang.hosting._launch_preparation"
    probes = (
        "from ...hosting._launch_preparation import _LaunchCapturePort",
        "from loushang.hosting import _launch_preparation",
        "from ...hosting import _launch_preparation",
    )
    for source in probes:
        imported = ast.parse(source).body[0]
        assert isinstance(imported, ast.ImportFrom)
        assert private_module in _resolve_import_from(ADAPTER, imported)
    consumers = {
        path
        for path in Path("src/loushang").rglob("*.py")
        if not path.is_relative_to(Path("src/loushang/hosting"))
        and private_module in _imports(path)
    }
    assert consumers == {ADAPTER}


def _test_functions(path: Path) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {
        node.name: node
        for node in ast.parse(_read(path), filename=str(path)).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_h6_4_managed_parity_matrix_is_executable_and_default_dark() -> None:
    record = _read(RECORD)
    normalized_record = " ".join(record.split())
    tests = _test_functions(WORKER_TESTS)
    required = (
        "test_hosting_adapter_maps_worker_and_publishes_atomic_session",
        "test_hosting_adapter_rechecks_abort_at_final_pre_spawn_fence",
        "test_hosting_adapter_preserves_managed_capture_and_worker_semantic_fence",
        "test_hosting_adapter_managed_capture_cancellation_retains_delegate_cleanup",
        "test_hosting_adapter_managed_preparation_runs_through_real_child_session",
        "test_hosting_adapter_managed_final_fence_failure_reclaims_real_child_session",
        "test_hosting_adapter_managed_capture_cancellation_reclaims_real_reservation",
        "test_owner_router_defaults_current_and_never_falls_back",
        "test_supervisor_can_handshake_through_hosting_aggregate",
    )
    for test_name in required:
        assert test_name in record
        test = tests[test_name]
        assert any(isinstance(node, ast.Assert) for node in ast.walk(test))
        assert not any("skip" in ast.unparse(item) for item in test.decorator_list)

    selection = _read(SELECTION)
    assert 'owner: WorkerSessionOwner = "current"' in selection
    assert "Current remains the default Worker owner" in normalized_record
    assert "not a claim that the Current Python Worker" in normalized_record
    assert "no Product composition supplies a Worker profile" in normalized_record


def test_h6_4_parity_record_pins_current_owner_evidence() -> None:
    record = _read(RECORD)
    current_evidence = (
        (
            CURRENT_LAUNCH_TESTS,
            "test_owner_only_worker_port_seals_identity_and_returns_redacted_evidence",
        ),
        (
            CURRENT_SUPERVISOR_TESTS,
            "test_supervisor_handshake_query_heartbeat_and_ordered_shutdown",
        ),
        (
            CURRENT_SUPERVISOR_TESTS,
            "test_launch_cancellation_is_not_collapsed_into_launch_failure",
        ),
        (
            CURRENT_SUPERVISOR_TESTS,
            "test_healthy_journal_failure_fences_and_cleans_owned_resources",
        ),
    )
    for path, test_name in current_evidence:
        assert f"{path.as_posix()}::{test_name}" in record
        test = _test_functions(path)[test_name]
        assert any(isinstance(node, ast.Assert) for node in ast.walk(test))


def test_h6_4_remote_hosting_gate_covers_adapter_and_deletion_guards() -> None:
    workflow = _read(WORKFLOW)
    lint = workflow.split("- name: Lint Hosting H0-H6", maxsplit=1)[1].split(
        "- name: Typecheck Hosting H0-H6", maxsplit=1
    )[0]
    typecheck = workflow.split(
        "- name: Typecheck Hosting H0-H6", maxsplit=1
    )[1].split("- name: Create H6.2 native report directory", maxsplit=1)[0]
    tests = workflow.split("- name: Test Hosting H0-H6 contract", maxsplit=1)[1]

    for source in (
        "src/loushang/harness/worker/__init__.py",
        "src/loushang/harness/worker/hosting_adapter.py",
        "src/loushang/harness/worker/owner_selection.py",
        "src/loushang/harness/worker/session.py",
        "src/loushang/harness/worker/supervisor.py",
    ):
        assert source in lint
        assert source in typecheck
    for test in (
        "tests/harness/worker/test_hosting_adapter.py",
        "tests/architecture/test_hosting_h5_worker_adapter.py",
        "tests/architecture/test_hosting_h6_harness_parity.py",
    ):
        assert test in lint
        assert test in tests
