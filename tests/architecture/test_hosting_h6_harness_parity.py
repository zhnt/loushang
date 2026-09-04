from __future__ import annotations

import ast
from pathlib import Path

RECORD = Path(
    "docs/internals/architecture/hosting/validation/"
    "managed-launch-preparation-h6-harness-parity.md"
)
ADAPTER = Path("src/loushang/harness/worker/hosting_adapter.py")
WORKER_TESTS = Path("tests/harness/worker/test_hosting_adapter.py")
SELECTION = Path("src/loushang/harness/worker/owner_selection.py")
HOSTING_PUBLIC = (
    Path("src/loushang/hosting/__init__.py"),
    Path("src/loushang/hosting/contracts.py"),
    Path("src/loushang/hosting/runtime.py"),
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _imports(path: Path) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(ast.parse(_read(path), filename=str(path))):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
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
    consumers = {
        path
        for path in Path("src/loushang").rglob("*.py")
        if not path.is_relative_to(Path("src/loushang/hosting"))
        and private_module in _imports(path)
    }
    assert consumers == {ADAPTER}


def test_h6_4_managed_parity_matrix_is_executable_and_default_dark() -> None:
    record = _read(RECORD)
    normalized_record = " ".join(record.split())
    worker_tests = _read(WORKER_TESTS)
    tree = ast.parse(worker_tests, filename=str(WORKER_TESTS))
    tests = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    required = (
        "test_hosting_adapter_maps_worker_and_publishes_atomic_session",
        "test_hosting_adapter_rechecks_abort_at_final_pre_spawn_fence",
        "test_hosting_adapter_preserves_managed_capture_and_worker_semantic_fence",
        "test_hosting_adapter_managed_capture_cancellation_retains_delegate_cleanup",
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
