from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
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
        expected_native_policy_closure_fingerprint=(
            expected_policy_closure or closure
        ),
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
            "payload-static-elf:sha256:"
            f"{worker_request.runtime.executable_digest}"
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
