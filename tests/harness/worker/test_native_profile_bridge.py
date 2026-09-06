from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from loushang.harness.resources.plugins.declarations import (
    PluginLocalWorkerConfiguration,
)
from loushang.harness.worker import (
    ManagedWorkerLaunchRequestV1,
    ProductWorkerActivationPolicyV1,
    ProductWorkerActivationReceiptV1,
    ProductWorkerNativeProfilePort,
    WorkerBindingError,
    WorkerLaunchIdentityV1,
    WorkerRuntimeBindingV1,
)
from loushang.harness.worker._native_profile_bridge import (
    _bind_posix_static_contained_product_worker_profile,
    _bind_windows_lpac_contained_product_worker_profile,
    _native_profile_prepared_request,
    _plan_windows_lpac_product_worker_profile,
    _WindowsLpacRuntimeBindings,
    _WindowsNativeContainmentSettlementWitness,
)
from loushang.harness.worker.hosting_adapter import (
    _map_worker_request,
    _worker_launch_preparation_port,
)
from loushang.hosting import (
    ProcessLaunchRequest,
    ProcessStderrMode,
    ProcessStdinMode,
    ProcessStdoutMode,
    ProcessStreamSpec,
)
from loushang.hosting._posix_launch_preparation import (
    _PosixStaticContainedLaunchCaptureSpec,
    _PosixStaticLaunchCaptureBackend,
)
from tests.harness.worker import test_product_activation as c51_evidence
from tests.harness.worker.test_hosting_adapter import _CapturePort
from tests.hosting import test_posix_launch_preparation as h6_posix_evidence

PLC9C5_C52_CASES = (
    "C52-EXACT-CLOSURE",
    "C52-CATALOG-MISMATCH",
    "C52-POLICY-CLOSURE-MISMATCH",
    "C52-EXEC-CLOSURE-MISMATCH",
    "C52-WSL-MICROSOFT-REJECT",
    "C52-UNKNOWN-CLASSIFIER-REJECT",
    "C52-NON-X86-REJECT",
    "C52-FD-SUBSTITUTION",
    "C52-CANCEL-PRE-EFFECT",
    "C52-CANCEL-POST-EFFECT",
    "C52-DESCENDANT-CLEANUP",
    "C52-SAMEBOOT-DEBT",
    "C52-CHANGEDBOOT-ABSENCE",
    "C52-SENTINEL-REDACTION",
)

_CATALOG_REVISION = "native-catalog-1"
_PROFILE_ID = "posix-static-contained-elf-v1"
_DIGEST_A = "a" * 64
_DIGEST_B = "b" * 64


def _platform(
    *,
    system: str = "Linux",
    machine: str = "x86_64",
    release: str = "6.8.0-generic",
    version: str = "Linux build",
):
    return lambda: (system, machine, release, version)


def _runtime(
    tmp_path: Path,
    *,
    sentinel: str = "payload",
    create: bool = True,
) -> WorkerRuntimeBindingV1:
    executable = tmp_path / sentinel
    if create:
        executable.write_bytes(b"worker-payload")
        executable.chmod(0o500)
    return WorkerRuntimeBindingV1.capture(
        package_root=tmp_path,
        configuration=PluginLocalWorkerConfiguration(
            entrypoint=sentinel,
            protocol="capability.query",
            protocol_version=1,
        ),
    )


def _identity(runtime: WorkerRuntimeBindingV1) -> WorkerLaunchIdentityV1:
    return WorkerLaunchIdentityV1(
        plugin_id="plugin.one",
        plugin_revision_digest=_DIGEST_A,
        contribution_id="capability.query",
        owner_id="coding.capability",
        product_id="coding",
        scope_id="scope-1",
        owner_generation=1,
        declaration_fingerprint=_DIGEST_A,
        worker_configuration_fingerprint=runtime.worker_configuration_fingerprint,
        attempt_id="1" * 32,
        supervisor_epoch=1,
        session_nonce="2" * 64,
    )


def _request(runtime: WorkerRuntimeBindingV1) -> ManagedWorkerLaunchRequestV1:
    return ManagedWorkerLaunchRequestV1(
        identity=_identity(runtime),
        runtime=runtime,
        validate_current=lambda: None,
    )


def _process_request(runtime: WorkerRuntimeBindingV1) -> ProcessLaunchRequest:
    return ProcessLaunchRequest(
        argv=(str(runtime.executable),),
        cwd=str(runtime.package_root),
        effective_environment=(),
        streams=ProcessStreamSpec(
            stdin=ProcessStdinMode.CLOSED,
            stdout=ProcessStdoutMode.DISCARD,
            stderr=ProcessStderrMode.PIPE,
        ),
    )


def _receipt(
    request: ManagedWorkerLaunchRequestV1,
    *,
    launcher_sha256: str,
    containment_profile_sha256: str,
    catalog_revision: str = _CATALOG_REVISION,
    expected_policy_closure: str | None = None,
) -> ProductWorkerActivationReceiptV1:
    closure = ProductWorkerActivationPolicyV1.native_policy_closure_fingerprint(
        native_profile_catalog_revision=catalog_revision,
        native_profile_id=_PROFILE_ID,
        payload_sha256=request.runtime.executable_digest,
        containment_launcher_sha256=launcher_sha256,
        containment_profile_sha256=containment_profile_sha256,
    )
    policy = ProductWorkerActivationPolicyV1(
        product_id=request.identity.product_id,
        product_runtime_id="runtime-1",
        product_scope_id=request.identity.scope_id,
        session_id="session-1",
        session_route="selected",
        selected_locator_fingerprint=_DIGEST_A,
        selected_locator_revision="locator-1",
        plugin_id=request.identity.plugin_id,
        plugin_revision_digest=request.identity.plugin_revision_digest,
        contribution_id=request.identity.contribution_id,
        reservation_fingerprint=_DIGEST_A,
        declaration_fingerprint=request.identity.declaration_fingerprint,
        worker_configuration_fingerprint=(
            request.identity.worker_configuration_fingerprint
        ),
        declared_required=True,
        effective_required=True,
        enabled=True,
        allowed_product_ids=(request.identity.product_id,),
        allowed_contribution_ids=(request.identity.contribution_id,),
        requested_owner="hosting",
        owner_selection_generation=1,
        no_fallback=True,
        native_profile_id=_PROFILE_ID,
        native_profile_catalog_revision=catalog_revision,
        allowed_native_profile_ids=(_PROFILE_ID,),
        expected_native_policy_closure_fingerprint=(expected_policy_closure or closure),
        product_policy_revision="policy-1",
        kill_switch_generation=1,
    )
    return ProductWorkerActivationReceiptV1(
        policy=policy,
        issue_sequence=1,
        issue_nonce="receipt-nonce-1",
    )


def _bound_profile(
    tmp_path: Path,
    *,
    platform_probe=None,
    catalog_revision: str = _CATALOG_REVISION,
    receipt_catalog_revision: str = _CATALOG_REVISION,
    expected_policy_closure: str | None = None,
    sentinel: str = "payload",
    native_fixture: bool = False,
) -> tuple[
    ProductWorkerNativeProfilePort,
    ProductWorkerActivationReceiptV1,
    ManagedWorkerLaunchRequestV1,
    ProcessLaunchRequest,
]:
    containment_profile_sha256 = hashlib.sha256(
        b"deny-network-and-process-group-escape"
    ).hexdigest()
    launcher = tmp_path / "containment-launcher"
    if native_fixture:
        h6_posix_evidence._compile_containment_launcher(
            launcher,
            profile_sha256=containment_profile_sha256,
        )
        h6_posix_evidence._compile_containment_payload(
            tmp_path / sentinel,
            marker="c52-admitted",
        )
    else:
        launcher.write_bytes(b"trusted-launcher")
        launcher.chmod(0o500)
    runtime = _runtime(tmp_path, sentinel=sentinel, create=not native_fixture)
    request = _request(runtime)
    launcher_sha256 = hashlib.sha256(launcher.read_bytes()).hexdigest()
    receipt = _receipt(
        request,
        launcher_sha256=launcher_sha256,
        containment_profile_sha256=containment_profile_sha256,
        catalog_revision=receipt_catalog_revision,
        expected_policy_closure=expected_policy_closure,
    )
    profile = _bind_posix_static_contained_product_worker_profile(
        receipt=receipt,
        worker_request=request,
        native_profile_catalog_revision=catalog_revision,
        launcher_path=launcher,
        launcher_sha256=launcher_sha256,
        containment_profile_sha256=containment_profile_sha256,
        _platform_probe=platform_probe or _platform(),
    )
    return profile, receipt, request, _process_request(runtime)


@pytest.mark.parametrize("case_id", PLC9C5_C52_CASES, ids=PLC9C5_C52_CASES)
def test_plc9c5_c52_linux_native_case(
    case_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if case_id == "C52-EXACT-CLOSURE":
        profile, receipt, worker_request, process_request = _bound_profile(
            tmp_path,
            native_fixture=True,
        )
        captured: list[object] = []
        backend = _PosixStaticLaunchCaptureBackend()

        async def capture(spec: object) -> object:
            assert isinstance(spec, _PosixStaticContainedLaunchCaptureSpec)
            material = await backend.capture(
                spec,
                attempt_id="c52-exact-closure",
                attempt_token=object(),
                on_capture=lambda value: None,
            )
            captured.append(material)
            return material

        async def exercise() -> object:
            binding = await profile.capture_native(process_request, capture=capture)
            await profile.verify_current()
            await binding.verify_current(process_request)  # type: ignore[attr-defined]
            await binding.close()  # type: ignore[attr-defined]
            await profile.close()
            return binding

        binding = asyncio.run(exercise())
        assert binding is not None
        assert len(captured) == 1
        material = captured[0]
        assert material.profile_id == receipt.policy.native_profile_id  # type: ignore[attr-defined]
        assert material.execution_closure[1] == (  # type: ignore[attr-defined]
            f"payload-static-elf:sha256:{worker_request.runtime.executable_digest}"
        )
        assert profile.receipt_fingerprint == receipt.fingerprint
        assert profile.worker_request_fingerprint == worker_request.fingerprint
        assert (
            profile.realized_native_policy_closure_fingerprint
            == receipt.policy.expected_native_policy_closure_fingerprint
        )
        assert len(profile.execution_closure_fingerprint) == 64

    elif case_id == "C52-CATALOG-MISMATCH":
        with pytest.raises(WorkerBindingError) as failure:
            _bound_profile(tmp_path, catalog_revision="native-catalog-2")
        assert failure.value.code == "worker_native_profile_catalog_mismatch"

    elif case_id == "C52-POLICY-CLOSURE-MISMATCH":
        with pytest.raises(WorkerBindingError) as failure:
            _bound_profile(tmp_path, expected_policy_closure=_DIGEST_B)
        assert failure.value.code == "worker_native_policy_closure_mismatch"

    elif case_id == "C52-EXEC-CLOSURE-MISMATCH":
        profile, _, _, process_request = _bound_profile(tmp_path)
        changed = replace(process_request, cwd=str(tmp_path / "changed"))
        called = False

        async def capture(spec: object) -> object:
            nonlocal called
            called = True
            return spec

        with pytest.raises(WorkerBindingError) as failure:
            asyncio.run(profile.capture_native(changed, capture=capture))
        assert failure.value.code == "worker_native_execution_closure_mismatch"
        assert not called

    elif case_id == "C52-WSL-MICROSOFT-REJECT":
        profile, _, _, process_request = _bound_profile(
            tmp_path,
            platform_probe=_platform(release="5.15.90.1-microsoft-standard-WSL2"),
        )
        with pytest.raises(WorkerBindingError) as failure:
            asyncio.run(profile.capture_native(process_request, capture=_never_capture))
        assert failure.value.code == "worker_native_platform_wsl_unsupported"

    elif case_id == "C52-UNKNOWN-CLASSIFIER-REJECT":
        profile, _, _, process_request = _bound_profile(
            tmp_path,
            platform_probe=lambda: ("Linux", "x86_64", "", "unknown"),
        )
        with pytest.raises(WorkerBindingError) as failure:
            asyncio.run(profile.capture_native(process_request, capture=_never_capture))
        assert failure.value.code == "worker_native_platform_unknown"

    elif case_id == "C52-NON-X86-REJECT":
        profile, _, _, process_request = _bound_profile(
            tmp_path,
            platform_probe=_platform(machine="aarch64"),
        )
        with pytest.raises(WorkerBindingError) as failure:
            asyncio.run(profile.capture_native(process_request, capture=_never_capture))
        assert failure.value.code == "worker_native_architecture_unsupported"

    elif case_id == "C52-FD-SUBSTITUTION":
        h6_posix_evidence.test_posix_contained_launcher_rejects_profile_substitution_before_payload(
            tmp_path
        )

    elif case_id == "C52-CANCEL-PRE-EFFECT":
        profile, _, _, process_request = _bound_profile(tmp_path)

        async def exercise() -> None:
            entered = asyncio.Event()

            async def capture(spec: object) -> object:
                del spec
                entered.set()
                await asyncio.Event().wait()
                raise AssertionError("unreachable")

            task = asyncio.create_task(
                profile.capture_native(process_request, capture=capture)
            )
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await profile.close()
            with pytest.raises(WorkerBindingError) as failure:
                await profile.verify_current()
            assert failure.value.code == "worker_native_profile_not_captured"

        asyncio.run(exercise())

    elif case_id == "C52-CANCEL-POST-EFFECT":
        h6_posix_evidence.test_posix_static_cancellation_after_os_create_reclaims_process(
            tmp_path,
            monkeypatch,
        )

    elif case_id == "C52-DESCENDANT-CLEANUP":
        h6_posix_evidence.test_posix_contained_profile_blocks_descendant_group_escape(
            tmp_path
        )

    elif case_id == "C52-SAMEBOOT-DEBT":
        c51_evidence.test_plc9c5_c51_contract_case("C51-CLEANUP-DEBT")

    elif case_id == "C52-CHANGEDBOOT-ABSENCE":
        c51_evidence.test_c51_registered_orphan_recovery_is_exact_idempotent_and_frees_cap(
            "C51-REGISTERED-RECOVERY",
            monkeypatch,
        )

    elif case_id == "C52-SENTINEL-REDACTION":
        sentinel = "secret-token-should-not-escape"
        profile, receipt, _, process_request = _bound_profile(
            tmp_path,
            sentinel=sentinel,
        )
        changed = replace(process_request, argv=(str(tmp_path / sentinel / "other"),))
        with pytest.raises(WorkerBindingError) as failure:
            asyncio.run(profile.capture_native(changed, capture=_never_capture))
        serialized = f"{failure.value}:{failure.value.code}:{receipt.to_dict()}"
        assert sentinel not in serialized
        assert str(tmp_path) not in serialized
        assert profile.execution_closure_fingerprint not in {"", _DIGEST_A}

    else:  # pragma: no cover - the manifest and architecture guard fix this set
        raise AssertionError(f"Unhandled PLC9C5 C5.2 case {case_id}")


async def _never_capture(spec: object) -> object:
    del spec
    raise AssertionError("unsupported platforms must reject before H6 capture")


def test_c52_profile_port_joins_existing_managed_h6_seam(tmp_path: Path) -> None:
    profile, _, worker_request, process_request = _bound_profile(tmp_path)
    assert process_request == _map_worker_request(worker_request)
    wrapped = _worker_launch_preparation_port(
        expected=process_request,
        worker_request=worker_request,
        delegate=profile,
        signal=None,
    )
    capture = _CapturePort()

    async def exercise() -> None:
        result = await wrapped.prepare_managed(  # type: ignore[attr-defined]
            process_request,
            capture,
        )
        assert len(capture.specs) == 1
        assert isinstance(capture.specs[0], _PosixStaticContainedLaunchCaptureSpec)
        await result.lease.verify_current()
        await result.lease.close()

    asyncio.run(exercise())


def test_windows_mechanics_profile_is_rejected_for_product_required_containment(
    tmp_path: Path,
) -> None:
    _, receipt, worker_request, _ = _bound_profile(tmp_path)
    windows_profile = "windows-restricted-direct-import-pe-v1"
    windows_policy = replace(
        receipt.policy,
        native_profile_id=windows_profile,
        allowed_native_profile_ids=(windows_profile,),
    )
    windows_receipt = replace(receipt, policy=windows_policy)

    with pytest.raises(WorkerBindingError) as failure:
        _bind_posix_static_contained_product_worker_profile(
            receipt=windows_receipt,
            worker_request=worker_request,
            native_profile_catalog_revision=(
                windows_policy.native_profile_catalog_revision
            ),
            launcher_path=tmp_path / "containment-launcher",
            launcher_sha256="1" * 64,
            containment_profile_sha256="2" * 64,
            _platform_probe=lambda: ("Windows", "AMD64", "10", "build"),
        )

    assert failure.value.code == "worker_native_profile_unsupported"


@dataclass(frozen=True, slots=True)
class _FakeWindowsProvisionSpec:
    request: ProcessLaunchRequest
    attempt_id: str
    operation_nonce: str
    lifecycle_fingerprint: str


@dataclass(frozen=True, slots=True)
class _FakeWindowsWitness:
    state: str
    attempt_id: str
    operation_nonce: str
    spec_fingerprint: str
    profile_fingerprint: str = "3" * 64
    sid_fingerprint: str = "4" * 64
    private_state_fingerprint: str = "5" * 64
    grant_digest: str = "6" * 64
    platform_identity: str = "windows-amd64-10.0.20348"


@dataclass(frozen=True, slots=True)
class _FakeWindowsCaptureSpec:
    request: ProcessLaunchRequest
    execution_closure: tuple[str, ...]


class _FakeWindowsCollision(RuntimeError):
    pass


class _FakeWindowsProvisioner:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.collision = False
        self.fail_delete_once = False

    def create_profile(self, spec, *, begin_effect):
        begin_effect()
        self.events.append("profile-create")
        if self.collision:
            raise _FakeWindowsCollision("foreign profile")
        return self._witness(spec, "PROFILE_CREATED")

    def apply_grants(self, spec, witness, *, begin_effect):
        assert witness.state == "PROFILE_CREATED"
        begin_effect()
        self.events.append("grant-apply")
        return replace(witness, state="GRANTS_APPLIED")

    def verify(self, spec, witness):
        del spec
        assert witness.state in {"GRANTS_APPLIED", "VERIFIED"}
        self.events.append("verify")
        return replace(witness, state="VERIFIED")

    def revoke_grants(self, spec, witness, *, begin_effect):
        del spec
        assert witness.state == "DEBT"
        begin_effect()
        self.events.append("grant-revoke")
        return replace(witness, state="GRANTS_REVOKED")

    def delete_profile(self, spec, witness, *, begin_effect):
        del spec
        assert witness.state == "GRANTS_REVOKED"
        begin_effect()
        self.events.append("profile-delete")
        if self.fail_delete_once:
            self.fail_delete_once = False
            raise RuntimeError("delete uncertainty")
        return replace(witness, state="PROFILE_DELETED")

    def settle(self, spec, witness):
        del spec
        assert witness.state == "PROFILE_DELETED"
        self.events.append("native-settle")
        return replace(witness, state="SETTLED")

    def mark_debt(self, spec, witness):
        del spec
        return replace(witness, state="DEBT")

    def recover_cleanup_witness(self, spec):
        self.events.append("recover-cleanup")
        return self._witness(spec, "DEBT")

    @staticmethod
    def _witness(spec, state: str) -> _FakeWindowsWitness:
        return _FakeWindowsWitness(
            state=state,
            attempt_id=spec.attempt_id,
            operation_nonce=spec.operation_nonce,
            spec_fingerprint=_DIGEST_B,
        )


class _NativeProvisioningStore:
    def __init__(self) -> None:
        self.document = None
        self.commit_then_raise_at_revision = None
        self.on_load = None

    def load(self):
        if self.on_load is not None:
            self.on_load()
        return None if self.document is None else json.loads(json.dumps(self.document))

    def compare_and_swap(self, *, expected_revision, document):
        current = 0 if self.document is None else self.document["stateRevision"]
        if current != expected_revision:
            return False
        self.document = json.loads(json.dumps(document))
        if self.commit_then_raise_at_revision == expected_revision:
            self.commit_then_raise_at_revision = None
            raise RuntimeError("commit result lost")
        return True


def _fake_windows_bindings(
    provisioner: _FakeWindowsProvisioner,
) -> _WindowsLpacRuntimeBindings:
    def build_provision_spec(request, **facts):
        return _FakeWindowsProvisionSpec(
            request=request,
            attempt_id=facts["attempt_id"],
            operation_nonce=facts["operation_nonce"],
            lifecycle_fingerprint=facts["lifecycle_fingerprint"],
        )

    def build_capture_spec(request, *, provision, witness):
        del provision, witness
        trusted = replace(
            request,
            effective_environment=(
                ("LOCALAPPDATA", r"C:\Users\u\AppData\Local"),
                ("SystemRoot", r"C:\Windows"),
                ("TEMP", r"C:\Users\u\AppData\Local\Temp"),
                ("TMP", r"C:\Users\u\AppData\Local\Temp"),
            ),
        )
        return _FakeWindowsCaptureSpec(
            request=trusted,
            execution_closure=(
                "capabilities:none",
                "all-application-packages:opt-out",
                f"provision:sha256:{_DIGEST_B}",
            ),
        )

    return _WindowsLpacRuntimeBindings(
        build_provision_spec=build_provision_spec,
        provisioner_factory=lambda: provisioner,
        build_capture_spec=build_capture_spec,
        spec_fingerprint=lambda spec: _DIGEST_B,
        witness_factory=_FakeWindowsWitness,
        profile_collision_type=_FakeWindowsCollision,
        capture_backend_id="windows-job-v1",
    )


def _windows_profile_context(tmp_path: Path):
    runtime = _runtime(tmp_path)
    request = _request(runtime)
    events: list[str] = []
    provisioner = _FakeWindowsProvisioner(events)
    bindings = _fake_windows_bindings(provisioner)
    probe = _platform(system="Windows", machine="AMD64", release="10.0.20348")
    plan = _plan_windows_lpac_product_worker_profile(
        worker_request=request,
        native_profile_catalog_revision=_CATALOG_REVISION,
        containment_launcher_sha256=_DIGEST_A,
        platform_imports=("KERNEL32.DLL",),
        _platform_probe=probe,
        _runtime_bindings=bindings,
    )
    base = _receipt(
        request,
        launcher_sha256=_DIGEST_A,
        containment_profile_sha256=plan.containment_profile_sha256,
    )
    policy = replace(
        base.policy,
        native_profile_id="windows-lpac-contained-pe-v1",
        allowed_native_profile_ids=("windows-lpac-contained-pe-v1",),
        expected_native_policy_closure_fingerprint=(
            plan.expected_native_policy_closure_fingerprint
        ),
    )
    receipt = ProductWorkerActivationReceiptV1(
        policy=policy,
        issue_sequence=1,
        issue_nonce="windows-lpac-receipt",
    )
    store = _NativeProvisioningStore()
    profile = _bind_windows_lpac_contained_product_worker_profile(
        receipt=receipt,
        worker_request=request,
        plan=plan,
        platform_imports=("KERNEL32.DLL",),
        provisioning_state_store=store,
        _platform_probe=probe,
        _runtime_bindings=bindings,
    )
    return profile, receipt, request, plan, store, provisioner, bindings, probe


def test_windows_lpac_profile_joins_plan_provision_capture_and_cleanup(
    tmp_path: Path,
) -> None:
    (
        profile,
        receipt,
        request,
        _,
        store,
        provisioner,
        _,
        _,
    ) = _windows_profile_context(tmp_path)
    process_request = _process_request(request.runtime)
    captured: list[object] = []

    async def capture(spec: object) -> object:
        captured.append(spec)
        return object()

    async def exercise() -> object:
        await profile.capture_native(process_request, capture=capture)
        await profile.verify_current()
        prepared = _native_profile_prepared_request(profile, process_request)
        assert prepared.streams.stderr is ProcessStderrMode.DISCARD
        assert dict(prepared.effective_environment)["SystemRoot"] == r"C:\Windows"
        await profile.close()
        return profile.native_containment_settlement_witness()

    settlement = asyncio.run(exercise())
    assert isinstance(settlement, _WindowsNativeContainmentSettlementWitness)
    assert settlement.receipt_fingerprint == receipt.fingerprint
    assert settlement.worker_request_fingerprint == request.fingerprint
    assert profile.cleanup_contract_version == 2
    assert profile.realized_native_policy_closure_fingerprint == (
        receipt.policy.expected_native_policy_closure_fingerprint
    )
    assert len(profile.execution_closure_fingerprint) == 64
    assert len(captured) == 1
    assert provisioner.events == [
        "profile-create",
        "grant-apply",
        "verify",
        "verify",
        "grant-revoke",
        "profile-delete",
        "native-settle",
    ]
    serialized = json.dumps(store.document, sort_keys=True)
    assert store.document["phase"] == "settled"
    assert str(tmp_path) not in serialized
    assert "S-1-" not in serialized


def test_windows_lpac_binding_is_noncommitting_until_capture_or_close(
    tmp_path: Path,
) -> None:
    profile, _, _, _, store, provisioner, _, _ = _windows_profile_context(tmp_path)

    assert store.document is None
    assert provisioner.events == []

    asyncio.run(profile.close())

    assert store.document["phase"] == "settled"
    assert provisioner.events == []


def test_windows_lpac_resumed_attempt_is_cleanup_only(tmp_path: Path) -> None:
    (
        first,
        receipt,
        request,
        plan,
        store,
        provisioner,
        bindings,
        probe,
    ) = _windows_profile_context(tmp_path)
    process_request = _process_request(request.runtime)
    asyncio.run(
        first.capture_native(process_request, capture=lambda spec: _return(spec))
    )
    resumed = _bind_windows_lpac_contained_product_worker_profile(
        receipt=receipt,
        worker_request=request,
        plan=plan,
        platform_imports=("KERNEL32.DLL",),
        provisioning_state_store=store,
        _platform_probe=probe,
        _runtime_bindings=bindings,
    )
    with pytest.raises(WorkerBindingError) as blocked:
        asyncio.run(
            resumed.capture_native(process_request, capture=lambda spec: _return(spec))
        )
    assert blocked.value.code == "worker_native_profile_cleanup_required"
    asyncio.run(resumed.close())
    assert store.document["phase"] == "settled"
    assert provisioner.events[-3:] == [
        "grant-revoke",
        "profile-delete",
        "native-settle",
    ]


def test_windows_lpac_cleanup_debt_is_retryable(tmp_path: Path) -> None:
    profile, _, request, _, store, provisioner, _, _ = _windows_profile_context(
        tmp_path
    )
    process_request = _process_request(request.runtime)
    asyncio.run(
        profile.capture_native(process_request, capture=lambda spec: _return(spec))
    )
    provisioner.fail_delete_once = True
    with pytest.raises(RuntimeError, match="delete uncertainty"):
        asyncio.run(profile.close())
    assert store.document["phase"] == "debt"
    asyncio.run(profile.close())
    assert store.document["phase"] == "settled"


def test_windows_lpac_journal_accepts_exact_commit_after_result_loss(
    tmp_path: Path,
) -> None:
    profile, _, request, _, store, _, _, _ = _windows_profile_context(tmp_path)
    store.commit_then_raise_at_revision = 1

    async def exercise() -> None:
        await profile.capture_native(
            _process_request(request.runtime),
            capture=lambda spec: _return(spec),
        )
        await profile.close()

    asyncio.run(exercise())
    assert store.document["phase"] == "settled"


def test_windows_lpac_reservation_result_loss_requires_cleanup_before_retry(
    tmp_path: Path,
) -> None:
    profile, _, request, _, store, provisioner, _, _ = _windows_profile_context(
        tmp_path
    )
    store.commit_then_raise_at_revision = 0

    with pytest.raises(WorkerBindingError) as rejected:
        asyncio.run(
            profile.capture_native(
                _process_request(request.runtime),
                capture=lambda spec: _return(spec),
            )
        )

    assert rejected.value.code == "worker_native_profile_cleanup_required"
    assert provisioner.events == []
    assert store.document["phase"] == "reserved"

    asyncio.run(profile.close())

    assert store.document["phase"] == "settled"
    assert provisioner.events == []


def test_windows_lpac_journal_rejects_store_callback_reentry(tmp_path: Path) -> None:
    profile, _, _, _, store, _, _, _ = _windows_profile_context(tmp_path)
    store.on_load = lambda: profile._journal.phase

    with pytest.raises(WorkerBindingError) as rejected:
        asyncio.run(profile.close())

    assert rejected.value.code == "worker_native_provisioning_store_reentered"


def test_windows_lpac_collision_never_mints_cleanup_authority(tmp_path: Path) -> None:
    profile, _, request, _, store, provisioner, _, _ = _windows_profile_context(
        tmp_path
    )
    provisioner.collision = True
    with pytest.raises(_FakeWindowsCollision):
        asyncio.run(
            profile.capture_native(
                _process_request(request.runtime),
                capture=lambda spec: _return(spec),
            )
        )
    asyncio.run(profile.close())
    assert store.document["phase"] == "settled"
    assert "grant-revoke" not in provisioner.events
    assert "profile-delete" not in provisioner.events


@pytest.mark.parametrize(
    ("observation", "code"),
    (
        (
            ("Linux", "x86_64", "5.15-microsoft-standard-WSL2", "WSL"),
            "worker_native_platform_wsl_unsupported",
        ),
        (
            ("Windows", "ARM64", "10.0.20348", "Windows"),
            "worker_native_architecture_unsupported",
        ),
        (
            ("Darwin", "x86_64", "23.0", "macOS"),
            "worker_native_platform_unsupported",
        ),
    ),
)
def test_windows_lpac_plan_rejects_unsupported_host_before_native_binding(
    tmp_path: Path,
    observation: tuple[str, str, str, str],
    code: str,
) -> None:
    request = _request(_runtime(tmp_path))
    used = False

    def build(*args, **kwargs):
        nonlocal used
        used = True
        raise AssertionError("unsupported host reached native binding")

    bindings = _WindowsLpacRuntimeBindings(
        build_provision_spec=build,
        provisioner_factory=lambda: object(),
        build_capture_spec=build,
        spec_fingerprint=lambda spec: _DIGEST_B,
        witness_factory=_FakeWindowsWitness,
        profile_collision_type=_FakeWindowsCollision,
        capture_backend_id="windows-job-v1",
    )
    with pytest.raises(WorkerBindingError) as rejected:
        _plan_windows_lpac_product_worker_profile(
            worker_request=request,
            native_profile_catalog_revision=_CATALOG_REVISION,
            containment_launcher_sha256=_DIGEST_A,
            platform_imports=("KERNEL32.DLL",),
            _platform_probe=lambda: observation,
            _runtime_bindings=bindings,
        )
    assert rejected.value.code == code
    assert not used


async def _return(value: object) -> object:
    return value
