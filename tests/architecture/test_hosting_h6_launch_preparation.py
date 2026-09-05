from __future__ import annotations

import ast
from pathlib import Path

HOSTING = Path("src/loushang/hosting")
CORE = HOSTING / "_launch_preparation.py"
CHILD_SESSION = HOSTING / "_child_session_host.py"
PROCESS_BACKEND = HOSTING / "_process_backend.py"
PROCESS_HOST = HOSTING / "_process_host.py"
ENDPOINT_HOST = HOSTING / "_endpoint_host.py"
PUBLIC_SURFACES = (
    HOSTING / "__init__.py",
    HOSTING / "contracts.py",
    HOSTING / "runtime.py",
)
FEASIBILITY = (
    Path("docs/internals/architecture/hosting/validation")
    / "managed-launch-preparation-h6-feasibility.md"
)
RUNTIME_TESTS = Path("tests/hosting/test_child_session_host.py")


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


def test_h6_1_core_is_private_default_dark_and_authority_free() -> None:
    core = _read(CORE)
    child_session = _read(CHILD_SESSION)
    process_backend = _read(PROCESS_BACKEND)
    public = "\n".join(_read(path) for path in PUBLIC_SURFACES)

    assert "__all__: list[str] = []" in core
    assert "launch_capture_backend" in child_session
    assert "launch_capture_backend" not in public
    for private_name in (
        "_LaunchCaptureSpec",
        "_OpaqueLaunchBinding",
        "_ManagedLaunchPreparationPort",
        "_CapturedLaunchMaterial",
        "_LaunchCaptureBackend",
        "_ReservationLaunchCapture",
        "_ManagedSpawnEffect",
        "_ManagedSpawnNotCreated",
        "_ManagedSpawnSettledWithoutProcess",
    ):
        assert private_name in core
        assert private_name not in public
    assert "_ManagedProcessPreparation" in process_backend
    assert "_ManagedProcessPreparation" not in public

    imports = (
        _imports(CORE)
        | _imports(CHILD_SESSION)
        | _imports(PROCESS_BACKEND)
        | _imports(PROCESS_HOST)
    )
    forbidden = (
        "loushang.harness",
        "loushang.coding",
        "loushang.apphost",
        "loushang.appserver",
        "loushang.appservice",
    )
    assert not any(name.startswith(forbidden) for name in imports)
    for authority_word in (
        "ApprovalReceipt",
        "Authorization",
        "WorkerLaunchAuthority",
        "PluginGeneration",
        "ProductId",
    ):
        assert authority_word not in core
        assert authority_word not in child_session


def test_h6_1_binding_and_state_are_request_attempt_backend_bound() -> None:
    core = _read(CORE)

    for field in (
        "request: ProcessLaunchRequest",
        "profile_id: str",
        "execution_closure: tuple[str, ...]",
        "attempt_id: str",
        "attempt_token: object",
        "backend_id",
        "binding._authority is not self",
        "binding._nonce is not self._binding_nonce",
        "self._spec.request != prepared_request",
        "material.request != self._spec.request",
        "material.attempt_id != self._attempt_id",
        "material.attempt_token is not self._attempt_token",
        "material.profile_id != self._spec.profile_id",
        "material.execution_closure != self._spec.execution_closure",
    ):
        assert field in core

    for state in (
        '"minted"',
        '"capturing"',
        '"captured"',
        '"verifying"',
        '"verified"',
        '"claimed"',
        '"attached"',
        '"closing"',
        '"closed"',
        '"faulted"',
        '"fenced"',
    ):
        assert state in core


def test_h6_1_transaction_attaches_then_uses_matched_backend_double_dispatch() -> None:
    core = _read(CORE)
    session = _read(CHILD_SESSION)
    process_host = _read(PROCESS_HOST)

    capture_body = core.split(
        "    async def capture(self, spec: _LaunchCaptureSpec)", maxsplit=1
    )[1].split("    def bind_result(", maxsplit=1)[0]
    assert capture_body.index("on_capture=self._attach") < capture_body.index(
        "return _OpaqueLaunchBinding"
    )
    assert session.index("attach_launch_capture") < session.index(
        "release_launch_capture"
    )
    assert "self._binding_nonce = object()" in core
    assert "class _ManagedLaunchPreparationPort(ABC)" in core
    assert "effect.begin_effect()" in _read(RUNTIME_TESTS)
    assert "if effect.accepts(failure):" in core
    assert "if effect.accepts_settled(failure):" in core
    assert "on_orphan_spawn(process)" in core
    assert "await self._material.spawn(" in core
    assert "isinstance(prepared, _ManagedProcessPreparation)" in process_host
    assert "await prepared.spawn_prepared(" in process_host
    assert "self._deferred.bind(endpoint.inheritance)" in session
    assert "await self._caller.verify_current()" in core
    assert "await self._material.verify_current(self.request)" in core
    assert "class _NestedCleanupDebt" in session
    assert "retained_cleanup_debt.settled(" in session
    assert "def _has_cleanup_debt(self, session_id: str)" in process_host
    assert "def _has_cleanup_debt(self, session_id: str)" in _read(ENDPOINT_HOST)
    assert "_find_cleanup_debt" not in session


def test_h6_1_fault_and_concurrency_matrix_is_executable() -> None:
    tests = _read(RUNTIME_TESTS)
    tree = ast.parse(tests, filename=str(RUNTIME_TESTS))
    async_tests = {
        node.name: node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
    }
    required_tests = (
        "test_managed_launch_joins_opaque_material_into_one_spawn_manifest",
        "test_managed_launch_callback_failure_after_capture_reclaims_before_endpoint",
        "test_managed_launch_cancellation_after_capture_reclaims_reservation",
        "test_managed_launch_capture_is_single_use_under_concurrency",
        "test_managed_launch_rejects_retarget_before_endpoint_acquisition",
        "test_managed_launch_rejects_cross_reservation_binding",
        "test_managed_launch_slot_bound_and_collision_fail_closed",
        "test_managed_launch_native_verify_failure_prevents_spawn",
        "test_managed_launch_backend_contract_mismatch_closes_both_materials",
        "test_managed_launch_cancelled_different_capture_retains_both_materials",
        "test_managed_launch_missing_attachment_is_salvaged_then_rejected",
        "test_managed_launch_close_waits_for_claimed_spawn_and_rejects_replay",
        "test_managed_launch_verify_and_close_share_one_owner_operation",
        "test_managed_launch_final_fence_cancellation_prevents_spawn",
        "test_managed_launch_ambiguous_spawn_cancellation_reclaims_every_owner",
        "test_managed_launch_host_close_waits_for_attached_capture",
        "test_managed_launch_cleanup_debt_is_retained_and_retried_on_host_close",
        "test_managed_launch_joined_owner_survives_endpoint_failure",
        "test_managed_launch_binding_is_consumed_by_the_first_bind",
        "test_managed_launch_attached_then_capture_error_reclaims_both_owners",
        "test_managed_launch_pre_attachment_error_acquires_no_native_owner",
        "test_managed_launch_orphan_cleanup_failure_is_owned_and_retried",
        "test_managed_launch_attempt_identity_is_unique_across_hosts",
        "test_managed_launch_cached_material_cannot_cross_attempt_tokens",
        "test_managed_launch_revalidates_identity_immediately_before_spawn",
        "test_managed_launch_concurrent_verify_is_one_use",
        "test_managed_launch_dual_cleanup_failure_retries_in_dependency_order",
        "test_managed_launch_unknown_spawn_outcome_fences_host_and_attempt",
        "test_managed_launch_cancelled_missing_spawn_callback_is_salvaged",
        "test_managed_launch_cancelled_different_spawn_retains_both_processes",
        "test_managed_launch_not_created_receipt_after_effect_fences_attempt",
        "test_managed_launch_missing_effect_gate_is_attached_then_fenced",
        "test_managed_launch_attachment_invalidates_forged_not_created_receipt",
        "test_managed_launch_transfer_fault_reclaims_process_but_keeps_fence",
        "test_managed_launch_recursive_start_cannot_bypass_reserved_capacity",
        "test_managed_launch_profile_identities_use_the_same_opaque_protocol",
        "test_managed_launch_private_process_seam_is_nominal_not_duck_typed",
        "test_managed_launch_private_caller_seam_is_nominal_and_default_dark",
    )
    for test_name in required_tests:
        test = async_tests[test_name]
        assert any(isinstance(node, ast.Assert) for node in ast.walk(test))
        decorators = {ast.unparse(decorator) for decorator in test.decorator_list}
        assert not any("skip" in decorator for decorator in decorators)

    makefile = _read(Path("Makefile"))
    assert "HOSTING_TEST_PATHS :=" in makefile
    assert "\ttests/hosting \\" in makefile


def test_h6_1_feasibility_record_separates_common_core_from_native_claims() -> None:
    record = " ".join(_read(FEASIBILITY).split())

    for statement in (
        "No production process is launched by these probes",
        "POSIX Mapping Probe",
        "Windows Mapping Probe",
        "common protocol",
        "synchronously register",
        "H6.2",
        "H6.3",
        "H6.4",
        "default-dark",
        "no public contract",
    ):
        assert statement.lower() in record.lower()
